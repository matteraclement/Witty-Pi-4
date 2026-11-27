# Witty-Pi-4

Witty Pi is an add-on board that adds realtime clock and power management to your Raspberry Pi. It can define your Raspberry Pi’s ON/OFF sequence, and significantly reduce the energy usage. Witty Pi 4 is the fourth generation of Witty Pi and it has these hardware resources onboard:

*   Factory calibrated and temperature compensated realtime clock with ±2ppm accuracy.
*   Dedicated temperature sensor with 0.125 °C resolution.
*   On-board DC/DC converter that accepts up to 30V DC.
*   AVR 8-bit microcontroller (MCU) with 8 KB programmable flash.

![](https://user-images.githubusercontent.com/6317566/174240816-01f8ac49-55d1-486a-bfef-b6471371125b.png)

Witty Pi 4 supports all Raspberry Pi models with 40-pin header, including A+, B+, 2B, Zero, Zero W, Zero 2 W, 3B, 3B+ and 4B.

### **References:**

*   [Witty Pi 4 Product Page](https://www.uugear.com/product/witty-pi-4/)
*   [Witty Pi 4 User Manual](https://www.uugear.com/doc/WittyPi4_UserManual.pdf)

### Temperature protection (software 4.26, firmware 12)

The current `scheduled-rev12` profile pairs firmware **12** with software **4.26**.
Temperature protection treats a failed LM75B read as no measurement: the firmware
skips the over/below-temperature action and leaves the RTC offset unchanged for
that pass, instead of decoding the failure as −1 °C. The menu's temperature
setters disarm the action, write the point, then arm the new action; a failed
point write leaves the action disabled. They write the LM75B limit mirror
(registers 52/53) as a complete two-byte word, which the firmware requires, so
the menu shows the new point immediately.

Every register, retained RTC trust and the scheduled contract are unchanged from
revision 11. Software 4.26 accepts revision 12 wherever 4.25 accepted revision 11;
software 4.25 rejects revision 12 and fails closed, so a revision-12 board needs
software 4.26. Revision-11 and older bundles do not contain these fixes.

### Retained RTC trust and scheduled shutdown (software 4.25, firmware 11)

The `scheduled-rev11` profile retains RTC trust across MCU resets. Virtual,
read-only register **74** returns exactly one byte: **0** untrusted or **1** trusted.
Reset, unknown and older retention markers fail closed. Ordinary time reads,
alarms and contract arming reject an untrusted calendar. Repair uses independently
accepted time without first reading the untrusted RTC. Before any calendar mutation,
the controller writes and verifies pending (`0x00`) in PCF85063A free RAM **0x03**;
clean (`0xa5`) is published only after complete STOP/frozen-calendar readback/
restart/control-and-validity verification. Raw writes through virtual register
**57** are blocked.
Armed or active contracts reject calendar mutation before touching the RTC or
retention marker. Timer2's active deadline remains independent of RTC trust.

The full-calendar command remains register **58**, one `w8@0x08` transaction.
The `scheduled-shutdown-v1` wire contract and controller-owned 60/120-second shutdown
limits are unchanged from revision 10. The normal target is 60 seconds after the
buffered ON boundary; 120 seconds is the total emergency limit. Register 21 retains
its older 25-second maximum for manual and protection paths. See the
[protocol and qualification boundary](Firmware/scheduled-contract.md).
Installing software does not flash a board or qualify its timing. Independent
scheduled enforcement requires explicit UTC migration and matching downstream
integration. Native Raspberry Pi behavior and historical WP4 bundles are unchanged;
retained trust is not backported to those bundles.

### Immutable vendor releases

[`release/`](release/) contains portable WP4 inputs for downstream integration:

| Bundle | Source commit | Firmware | Build evidence |
| --- | --- | --- | --- |
| [`wp4-4.26-fw12-4f7c60d444d9`](release/wp4-4.26-fw12-4f7c60d444d9/) | `4f7c60d444d9` | Revision 12, `scheduled-rev12` | Fresh pinned rebuilds match committed HEX; standard/Mini 8142 bytes, L3V7 8110 bytes, each 174 bytes static RAM; failed LM75B reads take no action, disarm-retarget-arm temperature setters with complete LM75B limit writes |
| [`wp4-4.25-fw11-286a7d43c1b4`](release/wp4-4.25-fw11-286a7d43c1b4/) | `286a7d43c1b4` | Revision 11, `scheduled-rev11` | Fresh pinned rebuilds match committed HEX; standard/Mini 8090 bytes, L3V7 8056 bytes, each 174 bytes static RAM; retained RTC trust and fail-closed read timeouts |
| [`wp4-4.24-fw10-234f89a73a42`](release/wp4-4.24-fw10-234f89a73a42/) | `234f89a73a42` | Revision 10, `scheduled-rev10` | All three pinned AVR rebuilds match committed HEX; standard/Mini 8172 bytes, L3V7 8136 bytes, each 209 bytes static RAM |
| [`wp4-4.23-fw7-d466cbc18aae`](release/wp4-4.23-fw7-d466cbc18aae/) | `d466cbc18aaea619c1f41ddb170789a661be3338` | Revision 7, `legacy-rev7` | Original committed HEX files, archived without rebuilding |
| [`wp4-4.23-fw9-8159567738cd`](release/wp4-4.23-fw9-8159567738cd/) | `8159567738cd020110f778a60e9f605ad37b56bf` | Revision 9, `atomic-rev9` | All three variants rebuilt with the pinned toolchain; LF-normalized HEX files match the committed files byte-for-byte |
| [`wp4-4.23-fw9-ca63d2145fa2`](release/wp4-4.23-fw9-ca63d2145fa2/) | `ca63d2145fa2826c455d6a690f52cfb8d085775c` | Revision 9, `atomic-rev9` | Fresh three-variant rebuild from the committed release-tooling revision; firmware hashes unchanged from `8159567` |

The revision-7 bundle preserves the fleet's source baseline, including its known
limitations; it is not a dump or attestation of any installed board. The revision-9
bundles contain the reboot/shutdown-state correction, coherent RTC reads, oscillator
validity and transport-failure handling, and atomic calendar writes.
`ca63d2145fa2` packages that same host software and firmware from the commit
introducing release tooling. All revision-7/9 bundles declare software **4.23**:
that version alone does not identify a release. The revision-10 bundle introduces
the scheduled contract with software **4.24**, but does not provide revision-11
retained trust. None establishes deployment or physical qualification.

Each directory contains:

- `release-manifest.json`: schema version 1, full source commit/tree and Git blob
  inventory, software version, explicit compatibility profile, expected products,
  artifact SHA-256/size, flash usage and provenance/qualification limits.
- `SHA256SUMS`: checksums for every other file in the bundle, including the manifest.
- `wittypi-software.tar.gz`: the exact committed `Software/wittypi/` tree under
  `wittypi/`, retaining executable modes. No host compilation is needed.
- `source.tar.gz`: the same commit's `Firmware/`, `Software/`, `README.md` and
  `LICENSE`; no nested release bundles or untracked build products.
- `WittyPi4.ino.hex`, `WittyPi4_Mini.ino.hex`, `WittyPi4_L3V7.ino.hex`: respectively
  standard `0x26`, Mini `0x36` and L3V7 `0x37` firmware, plus the unchanged `LICENSE`.
- `build-verification.json` only for a successfully rebuilt bundle: observed
  toolchain, commands, compiler output, hashes and flash/static-RAM usage.

AVR `objcopy` emits CRLF text while Git stores these HEX files with LF. Rebuilds
normalize only those line endings, never record contents, addresses or firmware
bytes. The receipt retains the raw compiler HEX hash/size/encoding and the
normalized artifact hash/size. A different record or byte rejects publication.

From the repository root, verify either copied bundle without Git, Arduino,
network access or hardware:

```sh
make verify RELEASE=release/wp4-4.23-fw7-d466cbc18aae
make verify RELEASE=release/wp4-4.23-fw9-8159567738cd
```

`sha256sum -c SHA256SUMS` inside either directory checks its file hashes. The
Python verifier additionally checks the manifest, HEX bounds/checksums, archive
safety, Git blob inventory, source/payload consistency and any build receipt.
Checksums prove integrity, not external authenticity: downstream consumers must
pin the reviewed manifest SHA-256.

#### Every change gets a new firmware revision or software version

Downstream integrations consume a bundle directory alone and identify a board by
its firmware revision. Therefore every released change to firmware source or HEX
increments `I2C_FW_REVISION` in both sketches and adds a matching profile in
`tools/release.py` (and the `Makefile` default); every released change to
`Software/wittypi/` increments `SOFTWARE_VERSION`. Host revision checks are
extended in the same change. `tools/release.py create` enforces the rule before
building: it refuses a bundle whose firmware revision is already published, in the
output root or this repository's `release/`, with different HEX, and one whose
pinned software version (revision 11 and later) is already published with a
different `Software/wittypi/` tree. Republishing identical firmware and software
from a later commit, such as a documentation fix, remains allowed. The revision-7
and revision-9 bundles predate the rule and share software 4.23 with different
trees.

To create a future release, first commit the intended software, source and
matching HEX files. With Arduino CLI, ATTinyCore **1.5.2** and AVR GCC
**7.3.0-atmel3.6.1-arduino7** already installed:

```sh
make release
```

A Git commit pins source; it does not automatically create a release. After
creation and verification, commit the generated release directory separately.
The manifest continues to identify the source commit used for the build. That
artifact-only commit keeps the checkout clean and does not require another
release; otherwise packaging would create an endless commit/release loop.

This defaults to committed `HEAD`, profile `scheduled-rev12`, output `release/` and
rebuilding all three variants. Revision 12 requires software **4.26**; revision 11
requires **4.25**.
`REF=<commit>`, `OUTPUT=/path/to/releases` and
`ARDUINO_CLI=/path/to/arduino-cli` override the source, destination and toolchain;
`PYTHON=/path/to/python3` selects Python. The release tool does not install packages
or alter Arduino configuration. It exports the resolved commit's Git objects,
not working-tree changes, and requires each generated HEX to match its committed
artifact. The historical profile preserves original binaries without rebuilding:

```sh
make release REF=d466cbc18aaea619c1f41ddb170789a661be3338 PROFILE=legacy-rev7
```

Creation refuses an existing destination, including the bundled examples above.
Use `OUTPUT=/path/to/new-release-root` for a separate export. The underlying
`python3 tools/release.py create --ref <commit> --profile <profile>` interface
remains available. The `scheduled-rev11` and `scheduled-rev12` profiles require
`--rebuild` and `rebuilt-byte-identical` provenance; neither creation nor offline
verification accepts an archived-only revision-11 or revision-12 bundle. Historical
profiles retain their original policy: omitting `--rebuild` archives committed
artifacts and explicitly records `archived-not-rebuilt`, not source-to-binary
verification. `make release` rebuilds `atomic-rev9`, `scheduled-rev10`,
`scheduled-rev11` and `scheduled-rev12`, and archives `legacy-rev7`. Profile
selection is an explicit maintainer review, not automatic ABI discovery. Only these
five explicitly named protocol profiles are
supported. Publication happens after verification; failed builds leave no final
release. Retain old directories while devices or rollback plans need them; never
edit a published bundle or choose a board's input by "newest".

#### Downstream and flashing boundaries

These are **unmanaged vendor scripts**, not DynAPI's patched
`install/wittypi_software`. Copying a bundle does not install it or enable revision
9 in DynAPI. A downstream integration must preserve managed clock/schedule and
shutdown ownership, retain revision-7 support and add revision-9 RTC transactions.
The standalone revision-9 host rejects revision-7 RTC operations; it is not a
drop-in replacement for the old fleet. `Software/install.sh` downloads UUGear's
network `LATEST`, not these pinned bundles, and must not be used as their installer.

WP4 exposes product ID and firmware revision, not a cryptographic build identity.
Revision 7 can be overridden by retained EEPROM; revision 9 comes from the running
image. Product ID can still be overridden by EEPROM in both. Record the actual
board variant and flashed artifact hash; a register read cannot prove a Git commit.
Within this repository's releases, each firmware revision names exactly one set
of three images.

Firmware flashing is a separate, authorized ISP maintenance operation, never a
release-tool action. Follow the [vendor procedure](https://www.uugear.com/portfolio/compile-flash-firmware-for-witty-pi-4/)
with a compatible programmer and the correct variant. Its erase/fuse procedure
uses `E:F5 H:DD L:E2`; do not assume that it preserves EEPROM. Before flashing,
record calibration (especially RTC offset register 37), settings and alarms, and
decide the EEPROM retention/reset policy. Recheck identity, calibration, settings,
clock synchronization, clean shutdown and real wake afterward. A matching build
or checksum is not electrical, timing or fleet qualification.

[`flash_wittypi4_from_standaloneraspberrypi/`](flash_wittypi4_from_standaloneraspberrypi/)
implements this procedure with a spare Raspberry Pi as ISP programmer: it verifies a
bundle offline, then flashes one variant and prints the expected identity registers.
It does not set the vendor fuses and the chip erase wipes EEPROM; read its README first.

The complete hardware-free suites are:

```sh
python3 -m unittest discover -s Firmware/tests -v
python3 -m unittest discover -s tools/tests -v
python3 -m unittest discover -s flash_wittypi4_from_standaloneraspberrypi/tests -v
```

These suites cover production firmware/host behavior and deterministic release
fixtures, including retained trust, profile/version admission, mandatory revision-11
and revision-12 rebuild evidence, refusal to republish a revision or pinned software
version with changed content, unchanged historical verification, corruption, unsafe archives,
working-tree isolation, failed-build cleanup, immutable destinations, compiler line
endings and AVR resource limits. Synthetic build receipts in tooling tests are not
AVR build evidence; only a real pinned-toolchain rebuild supplies that evidence.


### Modify the Firmware:
If you want to change the behavior of Witty Pi 4, you can modify the firmware, compile it and upload to your Witty Pi 4.

To compile the firmware, you need to install [ATtinyCore (V1.5.2)](https://github.com/SpenceKonde/ATTinyCore) in your Arduino IDE.

Here are the configurations on your Arduino IDE:

![](https://github.com/uugear/Witty-Pi-4/raw/main/Firmware/WittyPi4_Arduino_Settings.png)

The local shutdown-state correction clears `turnOffFromTXD` when a reboot has
consumed the TXD shutdown request, and on power cut. It prevents the next button,
alarm or protection-triggered shutdown from being mistaken for another reboot.
The Mini uses the `WittyPi4` sketch with `WITTY_PI_4_MINI` defined (product ID
`0x36`); standard builds remain `0x26`, and `WittyPi4_L3V7` remains `0x37`.
Firmware revision **9** added atomic RTC calendar writes alongside the coherent
reads introduced in revision 8. Revision **10** added the scheduled contract;
revision **11** adds retained RTC trust without changing either wire command.

For current source, use the exact pinned ATTinyCore **1.5.2** / AVR GCC
**7.3.0-atmel3.6.1-arduino7** build profile in `tools/build_firmware.py`. It builds
standard, Mini and L3V7 in isolated directories, applies LTO, linker relaxation and
the scheduled profile's size-oriented compiler flags, and records flash/static-RAM
usage for each variant. `make release` rebuilds the committed source, not dirty
working-tree edits, and rejects any committed HEX that differs from its rebuild.
Do not use a revision-9 compile command or resource count for revision 11 or later; use the
new bundle's verified build receipt. The build refuses flash or static-RAM overflow,
but does not measure peak stack use.

Before committing changed source and HEX, build the working checkout from the
repository root into a new or empty output directory:

```sh
python3 - <<'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, "tools")
from build_firmware import build_firmware
output = Path("/tmp/wp4-rev12-build")
receipt = build_firmware(Path("."), output, "arduino-cli")
(output / "build-verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
PY
```

Review the receipt and use its three HEX outputs for the matching committed
firmware paths. After committing those inputs, `make release REF=<source-commit>`
performs a fresh rebuild of that immutable snapshot and requires byte identity.
The preliminary working-tree receipt is not substituted for the bundle receipt.

`python3 -m unittest discover -s Firmware/tests -v` exercises production handlers
and RTC/contract behavior. These checks and AVR builds are offline evidence only;
no board has been flashed or physically qualified by the release tools.

To upload the firmware to Witty Pi, you can follow [this document](https://www.uugear.com/portfolio/compile-flash-firmware-for-witty-pi-4/).

### RTC calendar protocol

Install the matching revision-9-or-newer firmware before using this software.
Reads require revision 8; calendar writes require revision 9. Unsupported
operations are rejected rather than falling back to individual calendar bytes.
The host requires `i2ctransfer` from `i2c-tools` and reads seven bytes in one
combined transaction:

```sh
i2ctransfer -y 1 w1@0x08 58 r7
```

The bytes are seconds (including OS), minutes, hours, day, weekday, month, and
year, in the RTC's register encoding. The MCU reads them in one internal-bus
access; alarm decisions likewise use one seconds-through-day access. This
preserves the PCF85063A's frozen calendar across rollovers, as required by
[datasheet section 7.4](https://www.nxp.com/docs/en/data-sheet/PCF85063A.pdf).
Historical profiles retain their existing local-time convention; managed scheduled
profiles require explicit UTC migration as described above.

System-to-RTC synchronization sends register 58 and all seven calendar bytes
in one `w8@0x08` transaction. The MCU forwards the complete calendar in one
internal-bus write, keeping the RTC counters frozen until all fields are set.
Incomplete or overlong calendar commands and individual calendar-field writes
are rejected without touching the RTC. Revision 11 and later also reject calendar mutation
while a scheduled contract is armed or active, and retain an untrusted state
through interrupted/failed writes and resets. Register 74 is virtual and read-only;
it does not expand the EEPROM-backed legacy register array into journal storage.
The advertised firmware revision comes from the running image, not an older
revision retained in EEPROM.

The host verifies the complete calendar after writing, allowing elapsed time
and one pending RTC tick. Failed transfers or verification leave `TIME_UNKNOWN`
unchanged and report failure. Atomicity prevents rollover between fields, not a
physical rollback; revision 11 and later instead keep trust invalid after an incomplete
transaction until an independently sourced, fully verified repair succeeds.

The seconds register's oscillator-stop (OS) flag is checked before converting
time. A flagged RTC cannot set Linux time or trigger firmware startup/shutdown
alarms. Rejected reads leave NTP and `TIME_UNKNOWN` unchanged. Revision 11 and later never
repair from an untrusted RTC read or clear a pending marker during boot-time
initialization; repair requires independently accepted time. Historical bundles
keep their original boot-time bad-time/zero-year initialization policy.

Internal address or register-pointer NACKs produce an empty receive buffer,
not stale/bus data. The bridge encodes that failure as `0xFF` bytes, which
cannot be valid RTC calendar fields. The host rejects that marker, incomplete
transfers, malformed BCD, and invalid dates before attempting synchronization.
A transport failure skips boot-time synchronization in both directions; it
is not treated as an uninitialized RTC.

RTC-to-system synchronization succeeds only if NTP can be disabled and Linux
accepts the new time. If setting the clock fails, the prior enabled NTP state
is restored; failure to restore it is reported explicitly. `TIME_UNKNOWN` is
updated only after a successful clock change. These checks do not detect
electrical corruption that happens to look like valid calendar data.

