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
Shutdown timing is unchanged. Firmware revision **8** adds coherent RTC reads.

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
Standard and Mini occupy **8,098 / 8,192 bytes** of flash; L3V7 occupies
**7,998 / 8,192 bytes**. All three use 223 / 512 bytes of static RAM.

`python3 -m unittest discover -s Firmware/tests -v` exercises the production
shutdown handlers, RTC rollover/alarm handling, and host calendar decoding.
These checks and AVR builds are offline evidence only; no board has been
flashed or physically qualified. The checked-in HEX images are rebuilt from
these sources with the configuration above.

To upload the firmware to Witty Pi, you can follow [this document](https://www.uugear.com/portfolio/compile-flash-firmware-for-witty-pi-4/).

### RTC read protocol

Install the matching revision-8-or-newer firmware before using this software.
Older firmware is rejected rather than falling back to inconsistent byte reads.
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

