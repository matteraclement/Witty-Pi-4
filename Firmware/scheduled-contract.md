# Revision 10 scheduled shutdown contract

This source profile implements a **60-second normal target and a 120-second total
emergency limit**, measured from the buffered end of the ON window, T. It is a new
capability. Revision 7/9 and the legacy register-21 delay keep their previous
meaning. Source/build verification does not establish physical qualification or
deployment.

## Ownership and transitions

The controller owns T and the elapsed countdown. Timer2 is dedicated to this
contract; Timer1 retains manual/protection behavior. A host timer is a prompt to
start cleanup, not the final cutoff authority. Heartbeats, TXD transitions, SYS_UP,
Linux reboot and repeated arm commands cannot extend an active cycle.

| Current state | Input | Result |
| --- | --- | --- |
| Idle/armed | New, future, ordered identity and valid RTC in UTC mode | Armed; publish journal before successful status readback |
| Armed/active | Identical arm | No change, no timer renewal, no journal write |
| Armed | RTC reaches or passes T | Active; account for whole seconds already elapsed |
| Armed | Exact cancel before T | Cancelled retained outcome |
| Active | Edit/cancel/reboot/SYS_UP/TXD | Contract remains active |
| Active | Exact late completion with elapsed <60 s | Normal; cut power, then retain outcome |
| Active | Exact late completion at 60..119 s | Late; cut power, then retain outcome |
| Active | Elapsed reaches 120 s, including an overflow pending during completion | Expired; cut power, then retain outcome |
| Armed/active | An earlier manual or protection cut | Unknown interruption; preserve the earlier protection policy |
| Terminal | Exact acknowledgement after durable host import | Idle, retaining the generation/due ordering fence |
| Any retained armed/active state | MCU reset | Cut during setup; retain unknown, never restart a grace interval |

Terminal means normal, late, expired, unknown or cancelled. A terminal result blocks
replacement until imported and acknowledged. There is one outstanding outcome;
it cannot silently be overwritten by a new cycle. A cancel received after T first
services activation. The source preserves the corrected TXD reboot-origin handling.

## Register protocol

Firmware revision register 12 is `0x0a`. Products are standard `0x26`, Mini `0x36`
and L3V7 `0x37`. The product/revision pair cannot attest an exact flashed binary;
installation must also retain the reviewed artifact and physical board identity.

Register **72** accepts one 11-byte I2C write, including the register index:

| Offset | Bytes | Meaning |
| --- | --- | --- |
| 0 | 1 | Register 72 |
| 1 | 1 | Protocol version 1 |
| 2 | 1 | Action: arm=1, cancel=2, late-complete=3, acknowledge=4, enable-UTC=5 |
| 3 | 2 | Controller incarnation, little endian |
| 5 | 2 | Desired generation, little endian |
| 7 | 4 | T as unsigned Unix UTC seconds, little endian; through 2099 |

Register **73** returns exactly 13 bytes: version, phase, reserved zero, UTC-mode
bit, the same 8-byte incarnation/generation/due identity, then elapsed whole seconds.
Phase values are idle=0, armed=1, active=2, normal=3, late=4, expired=5, unknown=6,
cancelled=7. The complete readback establishes acceptance; I2C acknowledgement alone
does not. Reserved bytes and contradictory phase/age records are invalid on the host.

The compact 16-bit generation must not wrap. An exhausted generation is unavailable
until explicit migration to a fresh identity space. The incarnation advances on
MCU reset, delaying that advance until a retained terminal event is acknowledged so
the event keeps its original identity. It does not advance for each normal cycle.
Exhausted incarnation zero remains unavailable through reset. With the same
generation, a new T must be strictly later. Same identity/different content is not
a new cycle. Late commands for prior identities cannot regain ownership.

## UTC migration and host completion

Register 13 is the retained clock-mode bit. It starts in legacy local-time mode.
The explicit enable-UTC action is accepted only while idle. The maintenance owner
must then write and independently verify a correct UTC calendar and UTC next wake
before arming. Setting the bit alone does not convert the RTC. Never migrate an
armed or active board or reinterpret an old local-time alarm as UTC.

Software 4.24 reads this mode for RTC calendar conversion. Legacy schedule scripts
and alarm editing refuse the managed UTC profile. The downstream owner programs
and verifies wake and the scheduled contract together. Unsupported or unreadable
profiles must remain visibly unprotected.

`Software/wittypi/shutdown_contract.py` supplies bounded status/arm/cancel/ack/UTC
transport. Its late-completion path checks `/proc/self/mountinfo` and `/proc/swaps`
twice, requires the root mount, rejects writable persistent or unknown filesystems
and active swap, and reports only the exact active identity. It performs no host
storage write afterward. Install the helper at `/usr/lib/wittypi/shutdown_contract.py`
and its executable `system-shutdown-contract` wrapper at
`/lib/systemd/system-shutdown/wp4-contract` through the matching downstream installer.
The wrapper runs only for final `poweroff`, under a two-second process budget.

This is **a report that visible filesystems reached a safe-to-cut condition**, not
proof of kernel halt, successful recordings or measured VOUT removal. Other final
shutdown hooks must be audited because systemd may run them concurrently. A helper
or I2C failure leaves the independent deadline intact. Early daemon notification,
TXD, missing SSH and a missing heartbeat never become clean-completion evidence.

On the next host boot, commit the outcome and its identity durably before exact
acknowledgement. Deadline expiry is an error; late completion is a warning. Reset,
invalid/missing retention and unavailable evidence are unknown outcomes, not a
diagnosis that Linux hung. Keep recording success separate from OS completion.

## Retention, resource work and limits

The journal uses EEPROM bytes 64..479 as 32 thirteen-byte slots. Each packed
12-byte payload has incarnation, generation, T, phase, elapsed, wrapping sequence
and CRC8; a separate `0xa5` commit marker is invalidated before payload writes and
published last. Scanning the newest valid sequence survives an interrupted update.
Only transitions write EEPROM; timer ticks do not. Slot rotation spreads marker
and payload wear. CRC8 is a corruption check, not an unconditional guarantee against
every possible electrical fault or arbitrary corrupted record. EEPROM exhaustion,
brownout behavior and the ISP erase/retention procedure require qualification.

Power removal precedes terminal EEPROM writes. Interruption before a result is
published recovers as unknown. An unacknowledged event retains its identity over
repeated resets. The controller must remain powered to finish the journal write.

All three images use the pinned ATTinyCore 1.5.2 / AVR GCC 7.3.0 profile in
`tools/build_firmware.py`; additional size-oriented compiler flags are explicit in
the build receipt and do not apply to older immutable profiles. Standard/Mini use
8,172 of 8,192 flash bytes, L3V7 8,136; static RAM is 209 of 512 bytes. The 303-byte
remainder includes stack requirements and is not a measured stack high-water mark.
The new receive/calendar frames and the legacy sleep/interrupt nesting paths need
stack high-water measurement on the bench. The build refuses flash/RAM overflow.

Resource savings share conversion/alarm paths, remove unused Stream inheritance,
use constant pin mapping with PWM outputs disabled, and replace floating point with
millivolt/milliamp arithmetic. Exhaustive ADC/calibration/threshold checks show no
delay of the low-voltage threshold decision; strict greater-than recovery can be
conservative by less than 1 mV. Negative calibrated telemetry clamps to zero instead
of wrapping unsigned bytes. All signed temperatures and RTC offsets reproduce the
previous temperature-compensation result. Internal software I2C clock stretching
has a finite timeout so a stuck internal peripheral cannot hold an ISR forever.

The actual interrupt vector is `TIMER2_OVF_vect`, with nominal 7,812 ticks per second
at 8 MHz/1024. Calendar polling, clock resolution, oscillator tolerance and bounded
interrupt latency mean 120 nominal seconds requires an explicit measured physical
tolerance. MCU failure, an invalid RTC before activation, total supply loss and
external back-power are outside an OS-failure guarantee. The source does not claim
that resetting a failed controller preserves an active monotonic timer.

## Verification and deployment gate

Run both Python suites and rebuild/verify all variants. Tests execute production
GPIO handlers and contract code, cover no-host activation/cut, completion/expiry
arbitration, after-T cancellation, repeated messages, legacy protection, reset,
incarnation exhaustion, calendar limits, all 15 journal interruption positions and
more than one sequence wrap across all 32 slots. Host tests verify wire identity,
replay, mount/swap rejection and readback. The integer and GPIO optimizations have
independent numeric/physical-mapping fixtures.

Before enabling a profile, measure normal shutdown under representative recording
and storage load, missing Linux shutdown, I2C loss, reboots, clock changes, retained
outcomes through MCU/supply interruptions, physical VOUT and subsequent wake. Record
exact firmware/host artifacts, wiring, oscillator timing bounds, calibration and
filesystem/recording results. No flashing or deployment occurs in these tools.
