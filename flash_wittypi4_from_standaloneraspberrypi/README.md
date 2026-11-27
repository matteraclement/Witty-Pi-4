# Flash a Witty Pi 4 from a standalone Raspberry Pi

Programs the Witty Pi 4 MCU (ATtiny841) over ISP, using a spare Raspberry Pi whose
GPIO header bit-bangs the programming lines through avrdude's `linuxgpio`
programmer. It flashes the HEX images of a bundle from [`../release/`](../release/)
after verifying that bundle offline. This is the manual, authorized ISP maintenance
step described in the top-level README; it is not part of the release tooling and
proves nothing about hardware qualification.

| Script | Does |
| --- | --- |
| `check.sh` | Read-only link test: prints MCU signature (`0x1e9315`) and fuses. Writes nothing. |
| `flash.sh [-y] <release-dir> <standard\|mini\|l3v7>` | Runs `tools/release.py verify` on the bundle, shows release/variant/SHA256, asks for confirmation, then flashes the variant's HEX. |
| `raspi-gpio.conf` | The `RasPi` programmer (pins below), appended at run time to a temporary copy of `/etc/avrdude.conf`. |

The variant → HEX file and product ID mapping comes from the bundle's
`release-manifest.json`; nothing is hardcoded per file name.

## Requirements (on the programmer Pi)

- Raspberry Pi OS **Bullseye or older**. The vendor notes that kernel 6.5+ (Bookworm)
  removed the sysfs GPIO that avrdude's `linuxgpio` programmer uses.
- `avrdude` 6.3 (Bullseye package), `python3`, `sudo` for the `pi` user.
- This folder, `tools/` and the bundle copied side by side, from the repository root:

```sh
rsync -aR --exclude __pycache__ flash_wittypi4_from_standaloneraspberrypi tools \
  release/wp4-4.26-fw12-4f7c60d444d9 pi@<programmer-host>:wp4/
```

## Wiring

Six DuPont wires from the programmer Pi to the Witty Pi 4 ICSP footprint (top side on
the full-size board; underneath the MCU on Mini and L3V7). Signal pins, BCM numbering:

| Signal | BCM GPIO | Header pin |
| --- | --- | --- |
| RESET | 12 | 32 |
| SCK | 24 | 18 |
| MOSI | 23 | 16 |
| MISO | 18 | 12 |

The other two wires are power and ground; follow the wiring plan on the
[vendor page](https://www.uugear.com/portfolio/compile-flash-firmware-for-witty-pi-4/).
To change the signal pins, edit `raspi-gpio.conf`.

## Procedure

Before touching the board, on the host Pi it is mounted on, record firmware revision,
RTC offset and settings (the erase below destroys them):

```sh
i2cget -y 1 0x08 12     # firmware revision
i2cget -y 1 0x08 37     # RTC offset
for r in $(seq 16 49); do printf "%d " $r; i2cget -y 1 0x08 $r; done > wp4_conf_backup.txt
```

Then on the programmer Pi, with the board wired:

```sh
cd ~/wp4/flash_wittypi4_from_standaloneraspberrypi
./check.sh
./flash.sh ../release/wp4-4.26-fw12-4f7c60d444d9 standard   # or mini / l3v7
./check.sh
```

`flash.sh` stops before touching the MCU if the bundle fails verification or the
confirmation (typing the variant name; `-y` skips it) is not given. Success is
`… bytes of flash written` followed by `… bytes of flash verified`: avrdude reads the
flash back and compares it with the HEX. Use the HEX of the board's own variant: a
Mini flashed with the standard image reports product ID `0x26` instead of `0x36`.

Afterwards, on the host Pi, confirm identity (`flash.sh` prints the expected values),
restore the RTC offset recorded above and recheck settings:

```sh
i2cset -y 1 0x08 37 0x77   # replace 0x77 with the value read before flashing
```

A revision-12 board needs software **4.26** on its host; 4.25 rejects it. Also recheck
clock synchronization, clean shutdown and a real wake, as the top-level README requires.

## What is and is not changed

- Flash is rewritten; EEPROM is erased as a side effect of the chip erase (the
  EEPROM-save fuse is not set on the board this was written against). Registers 16–49
  return to firmware defaults.
- **Fuses are not touched.** The vendor command additionally writes `E:F5 H:DD L:E2`
  (brown-out detection at 2.7 V). `check.sh` prints the board's fuses
  (`safemode: Fuses OK (E:.., H:.., L:..)`); compare them with those values. Setting
  them is a deliberate step from the vendor page, not done by these scripts.

## Overrides and tests

| Variable | Default | Purpose |
| --- | --- | --- |
| `AVRDUDE_CMD` | `sudo avrdude` (`avrdude` as root) | Replace the avrdude command. |
| `AVRDUDE_BASE_CONF` | `/etc/avrdude.conf` | System config that `raspi-gpio.conf` is appended to. |
| `PYTHON` | `python3` | Interpreter for the bundle verifier. |
| `RELEASE_TOOL` | `../tools/release.py` | Bundle verifier. |

The tests use a fake avrdude and need no GPIO, root or hardware:

```sh
python3 -m unittest discover -s flash_wittypi4_from_standaloneraspberrypi/tests -v
```
