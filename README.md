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

### Immutable vendor releases

[`release/`](release/) contains portable WP4 inputs for downstream integration:

| Bundle | Source commit | Firmware | Build evidence |
| --- | --- | --- | --- |
| [`wp4-4.23-fw7-d466cbc18aae`](release/wp4-4.23-fw7-d466cbc18aae/) | `d466cbc18aaea619c1f41ddb170789a661be3338` | Revision 7, `legacy-rev7` | Original committed HEX files, archived without rebuilding |
| [`wp4-4.23-fw9-8159567738cd`](release/wp4-4.23-fw9-8159567738cd/) | `8159567738cd020110f778a60e9f605ad37b56bf` | Revision 9, `atomic-rev9` | All three variants rebuilt with the pinned toolchain; LF-normalized HEX files match the committed files byte-for-byte |

The first bundle preserves the fleet's source baseline, including its known
limitations; it is not a dump or attestation of any installed board. The second
contains the reboot/shutdown-state correction, coherent RTC reads, oscillator
validity and transport-failure handling, and atomic calendar writes. Both host
trees still declare software **4.23**: that version alone does not identify a
release. Neither bundle establishes deployment or physical qualification.

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

This defaults to committed `HEAD`, profile `atomic-rev9`, output `release/` and
rebuilding all three variants. `REF=<commit>`, `OUTPUT=/path/to/releases` and
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
remains available; omitting its `--rebuild` flag archives committed artifacts and
explicitly records `archived-not-rebuilt`, not source-to-binary verification.
`make release` always rebuilds `atomic-rev9` and archives `legacy-rev7`. Profile
selection is an explicit maintainer review, not automatic ABI discovery. Only the
two listed protocol profiles are supported. Publication happens after verification;
failed builds leave no final release. Retain old directories while devices or
rollback plans need them; never edit a published bundle or choose a board's input
by "newest".

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

Firmware flashing is a separate, authorized ISP maintenance operation, never a
release-tool action. Follow the [vendor procedure](https://www.uugear.com/portfolio/compile-flash-firmware-for-witty-pi-4/)
with a compatible programmer and the correct variant. Its erase/fuse procedure
uses `E:F5 H:DD L:E2`; do not assume that it preserves EEPROM. Before flashing,
record calibration (especially RTC offset register 37), settings and alarms, and
decide the EEPROM retention/reset policy. Recheck identity, calibration, settings,
clock synchronization, clean shutdown and real wake afterward. A matching build
or checksum is not electrical, timing or fleet qualification.

The complete hardware-free suites are:

```sh
python3 -m unittest discover -s Firmware/tests -v
python3 -m unittest discover -s tools/tests -v
```

The packaged revision-9 build was verified for all three variants. Firmware
regressions cover 14 tests; release/build regressions cover 29 tests, including
corruption, unsafe archives, working-tree isolation, failed-build cleanup,
immutable destinations, compiler line endings and AVR resource limits.


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
Shutdown timing is unchanged. Firmware revision **9** adds atomic RTC calendar
writes alongside the coherent reads introduced in revision 8.

Compile from this checkout with ATTinyCore **1.5.2**, AVR GCC
**7.3.0-atmel3.6.1-arduino7**, LTO and linker relaxation:

```sh
arduino-cli compile \
  --fqbn 'ATTinyCore:avr:attinyx41:chip=841,clock=8internal,pinmapping=old,LTO=enable,wiremode=slave,neopixelport=porta,millis=disabled,eesave=aenable,bod=2v7,bodact=enabled,bodpd=enabled' \
  --build-property compiler.c.elf.extra_flags=-Wl,--relax \
  --output-dir /tmp/wp4-standard Firmware/WittyPi4
```

For Mini, add `--build-property compiler.cpp.extra_flags=-DWITTY_PI_4_MINI`
and select a different output directory. For L3V7, select
`Firmware/WittyPi4_L3V7` without the Mini define.
Standard and Mini occupy **8,174 / 8,192 bytes** of flash; L3V7 occupies
**8,074 / 8,192 bytes**. All three use 223 / 512 bytes of static RAM.

`python3 -m unittest discover -s Firmware/tests -v` exercises the production
shutdown handlers, RTC read/write rollovers, rejected partial calendar writes,
firmware upgrades with retained EEPROM, oscillator validity, internal I2C
NACK/recovery, malformed host reads, and synchronization failure behavior.
These checks and AVR builds are offline evidence only; no board has been
flashed or physically qualified. The checked-in HEX images are rebuilt from
these sources with the configuration above.

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
RTC values retain the existing local-time convention.

System-to-RTC synchronization sends register 58 and all seven calendar bytes
in one `w8@0x08` transaction. The MCU forwards the complete calendar in one
internal-bus write, keeping the RTC counters frozen until all fields are set.
Incomplete or overlong calendar commands and individual calendar-field writes
are rejected without touching the RTC. Other RTC register writes are unchanged.
The advertised firmware revision comes from the running image, not an older
revision retained in EEPROM.

The host verifies the complete calendar after writing, allowing elapsed time
and one pending RTC tick. Failed transfers or verification leave `TIME_UNKNOWN`
unchanged and report failure. Atomicity here prevents rollover between fields;
it does not provide rollback after power loss or a mid-transfer electrical fault.

The seconds register's oscillator-stop (OS) flag is checked before converting
time. A flagged RTC cannot set Linux time or trigger firmware startup/shutdown
alarms. Rejected reads leave NTP and `TIME_UNKNOWN` unchanged. The boot-time
bad-time check includes OS as well as the existing zero-year initialization
check; its existing system-to-RTC initialization policy is unchanged.

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

