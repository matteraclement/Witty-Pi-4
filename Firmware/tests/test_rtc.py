"""RTC read-path regressions using production handlers and shell functions.

Run with the other offline firmware tests. The peripheral is simulated; this
checks calendar/transport behavior, not AVR timing or electrical operation.
"""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from test_firmware_handlers import ROOT, extract

SOFTWARE = ROOT.parent / "Software" / "wittypi" / "utilities.sh"

PERIPHERAL = r"""
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstddef>
#include <vector>
using byte = unsigned char;
using boolean = bool;
#define _SOFTIICMASTER_H 1
#define I2C_WRITE 0
#define I2C_READ 1
byte rtc[18], nextRtc[18], pointerReg;
bool expectPointer, reading, rollover;
int clicks;
bool i2c_init_() { return true; }
bool i2c_start_(uint8_t) { expectPointer=true; reading=false; return true; }
bool i2c_rep_start_(uint8_t address) {
  reading=address & 1;
  if (!reading) expectPointer=true;
  return true;
}
bool i2c_write_(uint8_t value) {
  if (expectPointer) { pointerReg=value; expectPointer=false; }
  else rtc[pointerReg++]=value;
  return true;
}
uint8_t i2c_read_(bool) { return rtc[pointerReg++]; }
void i2c_stop_() {
  // PCF85063A freezes the counters for the access, not across separate reads.
  if (reading && rollover) {
    for (int i=0; i<18; ++i) rtc[i]=nextRtc[i];
    rollover=false;
  }
  reading=false;
}
"""

HANDLER_STUBS = r"""
SoftWireMaster softWireMaster;
byte i2cReg[256];
char i2cIndex;
bool powerIsOn=true, turningOff=false, systemIsUp=true;
byte alarm1Delayed;
struct HostBus {
  std::vector<byte> response;
  void write(int value) { response.push_back(value); }
} TinyWireS;
float getInputVoltage() { return 0; }
float getOutputVoltage() { return 0; }
float getOutputCurrent() { return 0; }
void updatePowerMode() {}
void updateRegister(byte reg, byte value) { i2cReg[reg]=value; }
bool canTriggerAlarm() { return true; }
void emulateButtonClick() { ++clicks; }
void reset_rtc_alarm() {}
void copyAlarm(byte) {}
"""

SCENARIOS = r"""
void loadCalendar(const byte* before, const byte* after) {
  for (int i=0; i<7; ++i) { rtc[4+i]=before[i]; nextRtc[4+i]=after[i]; }
  rollover=true;
}
int main() {
  softWireMaster.begin();
  const byte before[][7] = {
    {0x59,0x34,0x12,0x28,0x03,0x10,0x26},
    {0x59,0x59,0x23,0x28,0x03,0x10,0x26},
    {0x59,0x59,0x23,0x31,0x04,0x12,0x26},
    {0x59,0x59,0x23,0x28,0x03,0x02,0x24},
  };
  const byte after[][7] = {
    {0x00,0x35,0x12,0x28,0x03,0x10,0x26},
    {0x00,0x00,0x00,0x29,0x04,0x10,0x26},
    {0x00,0x00,0x00,0x01,0x05,0x01,0x27},
    {0x00,0x00,0x00,0x29,0x04,0x02,0x24},
  };
  for (int c=0; c<4; ++c) {
    loadCalendar(before[c], after[c]);
    TinyWireS.response.clear();
    i2cIndex=I2C_RTC_SECONDS;
    requestEvent();
    assert(TinyWireS.response == std::vector<byte>(before[c], before[c]+7));
    for (byte b : TinyWireS.response) std::printf("0x%02x ", b);
    std::puts("");
  }
  loadCalendar(before[0], after[0]);
  i2cReg[I2C_CONF_DAY_ALARM2]=0x28;
  i2cReg[I2C_CONF_HOUR_ALARM2]=0x12;
  i2cReg[I2C_CONF_MINUTE_ALARM2]=0x35;
  i2cReg[I2C_CONF_SECOND_ALARM2]=0x59;
  processAlarmIfNeeded();
  assert(!turningOff && clicks==0 && !i2cReg[I2C_ALARM2_TRIGGERED]);
  // A plausible calendar is unusable while the oscillator-stop flag is set.
  rtc[4]=0xd9;
  processAlarmIfNeeded();
  assert(!turningOff && clicks==0 && !i2cReg[I2C_ALARM2_TRIGGERED]);
  rtc[4]=0x59;
  processAlarmIfNeeded();
  assert(turningOff && clicks==1 && i2cReg[I2C_ALARM2_TRIGGERED]);

  powerIsOn=false;
  i2cReg[I2C_CONF_DAY_ALARM1]=0x28;
  i2cReg[I2C_CONF_HOUR_ALARM1]=0x12;
  i2cReg[I2C_CONF_MINUTE_ALARM1]=0x35;
  i2cReg[I2C_CONF_SECOND_ALARM1]=0x59;
  rtc[4]=0xd9;
  processAlarmIfNeeded();
  assert(clicks==1 && !i2cReg[I2C_ALARM1_TRIGGERED]);
  rtc[4]=0x59;
  processAlarmIfNeeded();
  assert(clicks==2 && i2cReg[I2C_ALARM1_TRIGGERED]);
}
"""

SHELL_DEVICE = r"""
lsb_release() { echo Debian; }
source "$1"
export LC_ALL=C TZ=UTC
log() { printf '%s\n' "$*" >&2; }
log2file() { printf '%s\n' "$*" >&2; }
i2cget() { echo "${REVISION:-0x08}"; }
i2ctransfer() { printf '%s\n' "$SNAPSHOT"; }
"""


def shell(command, snapshot, **environment):
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", SHELL_DEVICE + command,
         "rtc-smoke", str(SOFTWARE)],
        env={**os.environ, "SNAPSHOT": snapshot, **environment},
        text=True, capture_output=True,
    )


class RtcReads(unittest.TestCase):
    def test_rollovers_through_firmware_and_host(self):
        expected = ["2026-10-28 12:34:59", "2026-10-28 23:59:59",
                    "2026-12-31 23:59:59", "2024-02-28 23:59:59"]
        for variant in ("WittyPi4", "WittyPi4_L3V7"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as d:
                directory = Path(d)
                (directory / "avr").mkdir()
                (directory / "avr/io.h").write_text("")
                (directory / "Arduino.h").write_text("")
                (directory / "Stream.h").write_text(
                    "class Print { public: void write(const char*) {} }; "
                    "class Stream: public Print {};\n")
                source = (ROOT / variant / (variant + ".ino")).read_text()
                defines = "\n".join(re.findall(
                    r"^#define (?:I2C_\w+|REASON_\w+|ADDRESS_\w+)\s+[^\n]+",
                    source, re.MULTILINE))
                handlers = "\n".join(extract(source, signature) for signature in (
                    "byte readFromDevice(", "byte bcd2dec(",
                    "long getTimestamp(", "void processAlarmIfNeeded()",
                    "void requestEvent()"))
                cpp = directory / "rtc.cpp"
                cpp.write_text(PERIPHERAL +
                    f'\n#include "{ROOT / variant / "SoftWireMaster.h"}"\n' +
                    defines + "\n" + HANDLER_STUBS + handlers + SCENARIOS)
                binary = directory / "rtc"
                subprocess.run([
                    *shlex.split(os.environ.get("CXX", "c++")), "-std=c++17",
                    "-O2", "-I", d, str(cpp), "-o", str(binary)], check=True)
                result = subprocess.run([str(binary)], text=True,
                                        capture_output=True, check=True)
                snapshots = result.stdout.splitlines()
                self.assertEqual(len(snapshots), len(expected))
                for snapshot, calendar in zip(snapshots, expected):
                    result = shell('ts=$(get_rtc_timestamp) || exit; '
                                   'date -d "@$ts" "+%Y-%m-%d %H:%M:%S"', snapshot)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), calendar)

    def test_old_firmware_is_rejected(self):
        result = shell("get_rtc_timestamp", "0x59 " * 7, REVISION="0x07")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


    def test_oscillator_stop_blocks_clock_sync(self):
        snapshot = "0xd6 0x34 0x12 0x28 0x03 0x10 0x26"
        result = shell("rtc_has_bad_time", snapshot)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "1"))
        result = shell("get_rtc_timestamp", snapshot)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        result = shell(
            'calls=0; sudo() { calls=$((calls+1)); }; TIME_UNKNOWN=1; '
            'rtc_to_system; status=$?; printf "%s %s %s\\n" '
            '"$status" "$TIME_UNKNOWN" "$calls"', snapshot)
        self.assertEqual(result.stdout.strip(), "1 1 0")

    def test_valid_oscillator_allows_clock_sync(self):
        snapshot = "0x56 0x34 0x12 0x28 0x03 0x10 0x26"
        result = shell("rtc_has_bad_time", snapshot)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "0"))
        result = shell(
            'sudo() { if [[ $1 == date ]]; then command date -d "$3" +%s; fi; }; '
            'TIME_UNKNOWN=1; rtc_to_system; status=$?; '
            'printf "%s %s\\n" "$status" "$TIME_UNKNOWN"', snapshot)
        self.assertEqual(result.stdout.strip(), "0 0")


if __name__ == "__main__":
    unittest.main()
