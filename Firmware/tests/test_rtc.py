"""RTC calendar regressions using production handlers and shell functions.

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
#include <cstdlib>
#include <ctime>
#include <string>
#define PROGMEM
#define pgm_read_byte(p) (*(p))
using byte = unsigned char;
using boolean = bool;
#define _SOFTIICMASTER_H 1
#define I2C_WRITE 0
#define I2C_READ 1
byte rtc[18], nextRtc[18], pointerReg;
bool expectPointer, reading, rollover, rtcAddress;
int clicks, nack, busReads, stops;
int faultAt=-1, operations;
bool corruptReadback;
struct Reset {};
void boundary() { if (operations++ == faultAt) throw Reset{}; }
int nackAt=-1, busOps;
int readErrorAt=-1, readOps;
bool rejectPending;
int writeTickAfter;
bool pendingTick;
byte bcd2dec(byte);
void tickCalendar() {
  std::tm time = {};
  time.tm_sec=bcd2dec(rtc[4]); time.tm_min=bcd2dec(rtc[5]);
  time.tm_hour=bcd2dec(rtc[6]); time.tm_mday=bcd2dec(rtc[7]);
  time.tm_mon=bcd2dec(rtc[9])-1; time.tm_year=bcd2dec(rtc[10])+100;
  std::time_t next=timegm(&time)+1;
  time=*gmtime(&next);
  int fields[]={time.tm_sec, time.tm_min, time.tm_hour, time.tm_mday,
                time.tm_wday, time.tm_mon+1, time.tm_year-100};
  for (int i=0; i<7; ++i) rtc[4+i]=(fields[i]/10)*16+fields[i]%10;
}
bool i2c_init_() { return true; }
bool i2c_start_(uint8_t address) {
  rtcAddress=(address>>1)==0x51; expectPointer=true; reading=false;
  return nack != 1;
}
bool i2c_rep_start_(uint8_t address) {
  reading=address & 1;
  if (!reading) expectPointer=true;
  return nack != 3;
}
bool i2c_write_(uint8_t value) {
  boundary();
  if (busOps++ == nackAt) return false;
  if (nack == 2) return false;
  if (expectPointer) { pointerReg=value; expectPointer=false; }
  else {
    if (rtcAddress && !(rejectPending && pointerReg==3 && value==0)) rtc[pointerReg]=value;
    ++pointerReg;
    if (writeTickAfter && pointerReg>=5 && pointerReg<=11 && --writeTickAfter == 0) pendingTick=true;
  }
  return true;
}
int i2c_read_(bool) {
  boundary();
  ++busReads;
  if (readOps++ == readErrorAt) return -1; // Low-level SCL timeout result.
  byte value=rtcAddress ? rtc[pointerReg++] : 0;
  if (corruptReadback && pointerReg==11) value^=1;
  return value;
}
// Faults happen inside the real SoftWireMaster transaction, not a model write.
void i2c_stop_() {
  ++stops;
  // Calendar ticks are deferred until STOP, including during writes.
  if (pendingTick && !(rtc[0] & 0x20)) { tickCalendar(); pendingTick=false; }
  // PCF85063A freezes the counters for the access, not across separate reads.
  if (reading && rollover && pointerReg>=8 && !(rtc[0] & 0x20)) {
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
bool locked;
struct Eeprom {
  byte values[512] = {};
  byte read(int index) { return values[index]; }
  void update(int index, byte value) {
    boundary();
    values[index]=value;
    boundary();
  }
} EEPROM;
void eeprom_update_byte(byte* address, byte value) { EEPROM.update(uintptr_t(address),value); }
bool calendarTrusted();
bool calendarPending();
void calendarWrite();
uint32_t calendarUtc(byte*);
bool contractLocked() { return locked; }
struct HostBus {
  std::vector<byte> response;
  std::vector<byte> request;
  size_t index=0;
  int available() { return request.size()-index; }
  int read() { return available() ? request[index++] : -1; }
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
void copyAlarm(byte);
bool contractActive() { return locked; }
void contractReply() {}
void contractReceive(int) {}
"""

SCENARIOS = r"""
void loadCalendar(const byte* before, const byte* after) {
  for (int i=0; i<7; ++i) { rtc[4+i]=before[i]; nextRtc[4+i]=after[i]; }
  rollover=true;
}
int main() {
  rtc[3]=nextRtc[3]=0xA5;
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

  for (int failure=1; failure<=3; ++failure) {
    // Seed unread data, then fail at write address, register pointer, or read address.
    nack=0;
    assert(readFromDevice(ADDRESS_RTC, 4, 7)==7);
    nack=failure; busReads=stops=0;
    assert(readFromDevice(ADDRESS_RTC, 4, 7)==0);
    assert(softWireMaster.available()==0 && softWireMaster.read()==-1);
    assert(busReads==0 && stops==1);
    assert(softWireMaster.endTransmission()==(failure==2 ? 3 : 2));

    TinyWireS.response.clear();
    i2cIndex=I2C_RTC_SECONDS;
    requestEvent();
    assert(TinyWireS.response==std::vector<byte>(7, 0xff));
    i2cReg[I2C_ALARM1_TRIGGERED]=0;
    processAlarmIfNeeded();
    assert(clicks==2 && !i2cReg[I2C_ALARM1_TRIGGERED]);

    // Recovery must not reuse the failed or previous receive buffer.
    nack=0; rtc[4]=0x12;
    assert(readFromDevice(ADDRESS_RTC, 4, 7)==7);
    assert(softWireMaster.read()==0x12);
    rtc[4]=0x59;
  }
  for (int failedByte=0;failedByte<7;++failedByte) {
    readOps=0; readErrorAt=failedByte;
    assert(readFromDevice(ADDRESS_RTC,4,7)==0);
    assert(softWireMaster.available()==0 && softWireMaster.read()==-1);
    assert(softWireMaster.endTransmission()==4);
  }
  readErrorAt=-1;
  // The internal-register-address overload must preserve a pointer-write NACK.
  nack=2;
  assert(softWireMaster.requestFrom(uint8_t(ADDRESS_RTC), uint8_t(7),
                                  uint32_t(4), uint8_t(1), uint8_t(1))==0);
  assert(softWireMaster.available()==0 && softWireMaster.read()==-1);
  assert(softWireMaster.endTransmission()==3);
}
"""

TRUST_SCENARIOS = r"""
const std::vector<byte> target={58,0x59,0x59,0x23,0x31,0x04,0x12,0x26};
void sendCalendar() {
  TinyWireS.request=target; TinyWireS.index=0; receiveEvent(8);
}
void boot() {
  // Volatile CPU/transport fields only, never retained RTC/EEPROM.
  softWireMaster.begin(); faultAt=-1; nackAt=-1; nack=0;
  corruptReadback=false; rejectPending=false; operations=busOps=0;
  readErrorAt=-1; readOps=0;
  TinyWireS.request.clear(); TinyWireS.response.clear(); TinyWireS.index=0;
}
void fixture() {
  boot(); locked=false; rollover=false; pendingTick=false; writeTickAfter=0;
  for (byte &b:rtc) b=0;
  rtc[0]=0x05; // Preserve unrelated CAP_SEL and CIE.
  rtc[7]=rtc[9]=1; rtc[10]=0x25;
  rtc[8]=3; // 2025-01-01 was Wednesday; the initial calendar is canonical.
  rtc[3]=0xA5;
}
void assertBlocked() {
  assert(!calendarTrusted());
  i2cIndex=58; TinyWireS.response.clear(); requestEvent();
  assert(TinyWireS.response==std::vector<byte>(7,255));
  int before=clicks; processAlarmIfNeeded(); assert(clicks==before);
}
int main() {
  fixture(); sendCalendar(); assert(calendarTrusted());
  int complete=operations;
  assert(rtc[0]==0x05 && calendarUtc(nullptr));
  for (int cut=0;cut<complete;++cut) {
    fixture(); faultAt=cut;
    try { sendCalendar(); } catch (const Reset&) {}
    faultAt=-1;
    bool committed=calendarTrusted();
    boot(); // MCU reset and host restart cannot restore pending trust.
    assert(calendarTrusted()==committed);
    if (committed) {
      assert(rtc[0]==0x05);
      assert(rtc[10]==0x25 || calendarUtc(const_cast<byte*>(target.data()+1)));
    } else assertBlocked();
    sendCalendar(); assert(calendarTrusted() && rtc[0]==0x05);
  }
  for (int n=0;n<24;++n) {
    fixture(); nackAt=n; sendCalendar(); boot();
    if (!calendarTrusted()) assertBlocked();
    sendCalendar(); assert(calendarTrusted());
  }
  for (int n=0;n<13;++n) {
    fixture(); readErrorAt=n; sendCalendar(); boot();
    if (n<12) assertBlocked(); // Includes pending, STOP, each byte, RUN and OS.
    sendCalendar(); assert(calendarTrusted());
  }
  fixture(); corruptReadback=true; sendCalendar(); assertBlocked();
  boot(); sendCalendar(); assert(calendarTrusted());
  fixture(); rejectPending=true; sendCalendar();
  assert(calendarTrusted() && rtc[10]==0x25 && rtc[0]==0x05);
  for (int marker: {0,1,0xA4,0xFF}) {
    fixture(); rtc[3]=marker; boot(); assertBlocked();
    sendCalendar(); assert(calendarTrusted());
  }
  fixture(); locked=true;
  auto before=std::vector<byte>(rtc,rtc+18);
  sendCalendar(); assert(operations==0 && rtc[3]==0xA5);
  assert(before==std::vector<byte>(rtc,rtc+18));
  for (int reg: {54,57,59,60,61,62,63,64}) {
    TinyWireS.request={byte(reg),0}; TinyWireS.index=0; receiveEvent(2);
    assert(before==std::vector<byte>(rtc,rtc+18));
  }
  locked=false;
  for (int tick=1;tick<=7;++tick) {
    fixture(); writeTickAfter=tick; sendCalendar();
    assert(calendarTrusted() && rtc[0]==0x05);
    assert(rtc[4]==0 && rtc[7]==1 && rtc[9]==1 && rtc[10]==0x27);
  }
  fixture(); TinyWireS.request={74,0}; TinyWireS.index=0; receiveEvent(2);
  assert(calendarTrusted()); // Virtual trust register is readonly.
  initializeRegisters(); assert(calendarTrusted());
  rtc[3]=0; initializeRegisters(); assertBlocked();
  fixture(); rtc[0]=0; rtc[3]=0; rtc[4]=0x80; boot(); assertBlocked();
  sendCalendar(); assert(calendarTrusted()); // Documented PCF power-reset defaults.
  for (int mode: {0x02,0x20,0x80,0xA2}) {
    fixture(); rtc[0]|=mode; assertBlocked();
    sendCalendar(); assert(calendarTrusted() && rtc[0]==0x05);
  }
  fixture(); rtc[4]|=0x80; assertBlocked();
  sendCalendar(); assert(calendarTrusted());
  fixture(); rtc[3]=0;
  TinyWireS.request={57,0xA5}; TinyWireS.index=0; receiveEvent(2); assertBlocked();
  fixture(); TinyWireS.request={54,rtc[0]}; TinyWireS.index=0; receiveEvent(2); assertBlocked();
  sendCalendar(); assert(calendarTrusted());
  fixture(); TinyWireS.request={58,0,0,0,0x30,1,0x02,0x26};
  TinyWireS.index=0; receiveEvent(8); assertBlocked();
  assert(rtc[0]&0x20); sendCalendar(); assert(calendarTrusted());
  fixture(); alarm1Delayed=3; assert(calendarPending() && !alarm1Delayed); assertBlocked();
  fixture();
  for (int i=0;i<4;++i) i2cReg[27+i]=0x10+i;
  copyAlarm(27);
  for (int i=0;i<4;++i) assert(rtc[11+i]==0x10+i);
  for (int v=0;v<256;++v) assert(bcd2dec(v)==(v/16*10+v%16));
  for (uint32_t day=0;day<65536;++day) for (int hour: {0,23,255})
    for (int minute: {0,59,255}) for (int second: {0,59,255})
      assert(getTimestamp(day,hour,minute,second)==(((day*24+hour)*60+minute)*60+second));
  std::printf("PASS retained calendar: %d reset boundaries, byte-NACKs, repair, STOP rollover\n",complete);
}
"""

WRITE_DEVICE = r"""
int main(int argc, char** argv) {
  assert(argc >= 5);
  softWireMaster.begin();
  const char* state=std::getenv("RTC_STATE");
  FILE* file=std::fopen(state, "rb");
  assert(file && std::fread(rtc, 1, sizeof rtc, file)==sizeof rtc);
  std::fclose(file);
  if (argv[argc-1][0] == 'r') {
    i2cIndex=std::strtol(argv[4], nullptr, 0);
    requestEvent();
    for (byte value : TinyWireS.response) std::printf("0x%02x ", value);
    std::puts("");
  } else {
    for (int i=4; i<argc; ++i)
      TinyWireS.request.push_back(std::strtol(argv[i], nullptr, 0));
    writeTickAfter=std::atoi(std::getenv("WRITE_TICK_AFTER"));
    nack=std::atoi(std::getenv("WRITE_NACK"));
    receiveEvent(TinyWireS.request.size());
    file=std::fopen(state, "wb");
    assert(file && std::fwrite(rtc, 1, sizeof rtc, file)==sizeof rtc);
    std::fclose(file);
  }
}
"""

WRITE_COMMANDS = r"""
get_sys_timestamp() { date -d "$SYSTEM_TIME UTC" +%s; }
i2ctransfer() {
  [[ ${TRANSFER_STATUS:-0} == 0 ]] || return 1
  if [[ $4 == 73 ]]; then echo '0x01 0x00 0x00 0x01 0x01 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00'; return; fi
  "$RTC_BRIDGE" "$@"
}
TIME_UNKNOWN=1
system_to_rtc
status=$?
printf '%s %s\n' "$status" "$TIME_UNKNOWN"
"""

SHELL_DEVICE = r"""
lsb_release() { echo Debian; }
source "$1"
export LC_ALL=C TZ=UTC
log() { printf '%s\n' "$*" >&2; }
log2file() { printf '%s\n' "$*" >&2; }
i2cget() {
  [[ ${I2C_STATUS:-0} == 0 ]] || return 1
  if [[ $4 == 74 ]]; then
    if [[ -n ${RTC_STATE:-} ]]; then
      local value
      value=$("$RTC_BRIDGE" -y 1 w1@0x08 74 r1) || return
      read -r value <<< "$value"
      printf '%s\n' "$value"
    else echo "${TRUST:-0x01}"; fi
  elif [[ $4 == 13 ]]; then echo 0x00
  else echo "${REVISION:-0x0b}"; fi
}
i2ctransfer() {
  [[ ${TRANSFER_STATUS:-0} == 0 ]] || return 1
  if [[ $4 == 73 ]]; then echo '0x01 0x00 0x00 0x01 0x01 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00'
  else printf '%s\n' "$SNAPSHOT"; fi
}
timedatectl() { echo "${NTP_STATE:-yes}"; return "${SHOW_STATUS:-0}"; }
sleep() { :; }
"""

CLOCK_COMMANDS = r"""
ntp=${NTP_STATE:-yes}
attempts=0
writes=0
sudo() {
  if [[ $1 == timedatectl ]]; then
    if [[ $3 == 0 ]]; then
      [[ ${FAIL_DISABLE:-0} == 1 ]] && return 1
      ntp=no
    else
      [[ ${FAIL_RESTORE:-0} == 1 ]] && return 1
      ntp=yes
    fi
  elif [[ $1 == date ]]; then
    attempts=$((attempts+1))
    [[ ${FAIL_DATE:-0} == 1 ]] && return 1
    command date -d "$3" +%s || return
    writes=$((writes+1))
  fi
}
TIME_UNKNOWN=1
rtc_to_system
status=$?
printf '%s %s %s %s %s\n' "$status" "$TIME_UNKNOWN" "$ntp" "$attempts" "$writes"
"""



def shell(command, snapshot, **environment):
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", SHELL_DEVICE + command,
         "rtc-smoke", str(SOFTWARE)],
        env={**os.environ, "SNAPSHOT": snapshot, **environment},
        text=True, capture_output=True,
    )



def compile_rtc(directory, variant, scenarios):
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
        "byte readFromDevice(", "byte writeToDevice(", "byte bcd2dec(",
        "uint32_t getTimestamp(", "long getAlarmTimestamp(", "void copyAlarm(", "void processAlarmIfNeeded()",
        "void initializeRegisters()", "void requestEvent()", "void receiveEvent("))
    contract = (ROOT / variant / "ScheduledContract.h").read_text()
    handlers += "\n" + "\n".join(extract(contract, signature) for signature in (
        "byte calendarByte(", "boolean calendarSetByte(", "boolean calendarTrusted()", "boolean calendarPending()",
        "uint32_t calendarUtc(", "void calendarWrite()"))
    cpp = directory / "rtc.cpp"
    cpp.write_text(PERIPHERAL +
        f'\n#include "{ROOT / variant / "SoftWireMaster.h"}"\n' +
        defines + "\n" + HANDLER_STUBS + handlers + scenarios)
    binary = directory / "rtc"
    subprocess.run([
        *shlex.split(os.environ.get("CXX", "c++")), "-std=c++17", "-fsigned-char",
        "-O2", "-I", str(directory), str(cpp), "-o", str(binary)], check=True)
    return binary

class RtcReads(unittest.TestCase):
    def test_managed_utc_profile_is_independent_of_host_timezone_and_rejects_legacy_edits(self):
        result = shell(r'''
i2cget() { if [[ $4 == 13 || $4 == 74 ]]; then echo 0x01; else echo 0x0b; fi; }
export TZ=Europe/Paris
get_rtc_timestamp
if set_startup_time 2 12 0 0; then exit 9; fi
if set_shutdown_time 2 12 0 0; then exit 10; fi
''', '0x00 0x00 0x12 0x01 0x00 0x11 0x26')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '1793534400')

    def test_rollovers_through_firmware_and_host(self):
        expected = ["2026-10-28 12:34:59", "2026-10-28 23:59:59",
                    "2026-12-31 23:59:59", "2024-02-28 23:59:59"]
        for variant in ("WittyPi4", "WittyPi4_L3V7"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as d:
                directory = Path(d)
                binary = compile_rtc(directory, variant, SCENARIOS)
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
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
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


    def test_invalid_snapshots_do_not_change_system_time(self):
        snapshots = [
            "", "0x00", "0x00 0x00 0x00 0x28 0x03 0x10",
            "0x00 0x00 0x00 0x28 0x03 0x10 0x26 0x00",
            "0xgg 0x00 0x00 0x28 0x03 0x10 0x26",
            "0x00 0x00 0x00 0x28\n0x03 0x10 0x26",
            "0xff " * 7,
            "0x00 0x1a 0x12 0x28 0x03 0x10 0x26",
            "0x60 0x00 0x00 0x28 0x03 0x10 0x26",
            "0x00 0x60 0x00 0x28 0x03 0x10 0x26",
            "0x00 0x00 0x24 0x28 0x03 0x10 0x26",
            "0x00 0x00 0x12 0x30 0x03 0x02 0x26",
            "0x00 0x00 0x12 0x28 0x03 0x00 0x26",
        ]
        for snapshot in snapshots:
            with self.subTest(snapshot=snapshot):
                result = shell(CLOCK_COMMANDS, snapshot)
                self.assertEqual(result.stdout.strip(), "1 1 yes 0 0", result.stderr)

    def test_transport_failure_does_not_mean_uninitialized_rtc(self):
        valid = "0x56 0x34 0x12 0x28 0x03 0x10 0x26"
        for snapshot, environment in [
            ("0xff " * 7, {}),
            (valid, {"TRANSFER_STATUS": "1"}),
            (valid, {"I2C_STATUS": "1"}),
        ]:
            with self.subTest(snapshot=snapshot, environment=environment):
                result = shell("rtc_has_bad_time", snapshot, **environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                result = shell(CLOCK_COMMANDS, snapshot, **environment)
                self.assertEqual(result.stdout.strip(), "1 1 yes 0 0", result.stderr)

    def test_i2c_read_failure_has_status_and_no_data(self):
        result = shell("i2c_read 1 8 12", "", I2C_STATUS="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_clock_command_failures_preserve_unknown_state(self):
        snapshot = "0x56 0x34 0x12 0x28 0x03 0x10 0x26"
        cases = [
            ({}, "0 0 no 1 1"),
            ({"SHOW_STATUS": "1"}, "1 1 yes 0 0"),
            ({"NTP_STATE": "unexpected"}, "1 1 unexpected 0 0"),
            ({"FAIL_DISABLE": "1"}, "1 1 yes 0 0"),
            ({"FAIL_DATE": "1"}, "1 1 yes 1 0"),
            ({"FAIL_DATE": "1", "NTP_STATE": "no"}, "1 1 no 1 0"),
            ({"FAIL_DATE": "1", "FAIL_RESTORE": "1"}, "1 1 no 1 0"),
        ]
        for environment, expected in cases:
            with self.subTest(environment=environment):
                result = shell(CLOCK_COMMANDS, snapshot, **environment)
                self.assertEqual(result.stdout.strip(), expected, result.stderr)


class RtcWrites(unittest.TestCase):
    def test_retained_transaction_faults_and_repairs(self):
        for variant in ("WittyPi4", "WittyPi4_L3V7"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as d:
                binary = compile_rtc(Path(d), variant, TRUST_SCENARIOS)
                subprocess.run([str(binary)], check=True)

    def test_rollovers_through_host_and_firmware(self):
        cases = [
            ("2026-10-28 12:34:59", "2026-10-28 12:35:00"),
            ("2026-10-28 23:59:59", "2026-10-29 00:00:00"),
            ("2026-12-31 23:59:59", "2027-01-01 00:00:00"),
            ("2024-02-28 23:59:59", "2024-02-29 00:00:00"),
            ("2026-11-01 12:00:00", "2026-11-01 12:00:01"),
        ]
        for variant in ("WittyPi4", "WittyPi4_L3V7"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as d:
                directory = Path(d)
                binary = compile_rtc(directory, variant, WRITE_DEVICE)
                state = directory / "rtc-state"
                for before, after in cases:
                    for tick_after in range(1, 8):
                        with self.subTest(before=before, tick_after=tick_after):
                            state.write_bytes(bytes(18))
                            result = shell(WRITE_COMMANDS, "", REVISION="0x0b",
                                RTC_BRIDGE=str(binary), RTC_STATE=str(state),
                                SYSTEM_TIME=before, WRITE_TICK_AFTER=str(tick_after),
                                WRITE_NACK="0")
                            self.assertEqual(result.stdout.strip(), "0 2", result.stderr)
                            snapshot = " ".join(f"0x{v:02x}" for v in state.read_bytes()[4:11])
                            result = shell('ts=$(get_rtc_timestamp) || exit; '
                                'date -u -d "@$ts" "+%Y-%m-%d %H:%M:%S"', snapshot)
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertEqual(result.stdout.strip(), after)
                            if before.startswith("2026-11-01"):
                                self.assertEqual(state.read_bytes()[8], 0)  # Sunday.

    def test_failed_writes_preserve_unknown_state(self):
        initial = bytes([0, 0, 0, 0, 0, 0, 0, 1, 3, 1, 0x25] + [0]*7)
        cases = [
            {"REVISION": "0x08"},
            {"I2C_STATUS": "1"},
            {"TRANSFER_STATUS": "1"},
            {"WRITE_NACK": "1"},
            {"WRITE_NACK": "2"},
        ]
        for variant in ("WittyPi4", "WittyPi4_L3V7"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as d:
                directory = Path(d)
                binary = compile_rtc(directory, variant, WRITE_DEVICE)
                state = directory / "rtc-state"
                for overrides in cases:
                    with self.subTest(overrides=overrides):
                        state.write_bytes(initial)
                        environment = dict(REVISION="0x0b", RTC_BRIDGE=str(binary),
                            RTC_STATE=str(state), SYSTEM_TIME="2026-12-31 23:59:59",
                            WRITE_TICK_AFTER="0", WRITE_NACK="0")
                        environment.update(overrides)
                        result = shell(WRITE_COMMANDS, "", **environment)
                        self.assertEqual(result.stdout.strip(), "1 1", result.stderr)
                        self.assertEqual(state.read_bytes(), initial)

    def test_partial_calendar_commands_do_not_modify_rtc(self):
        calendar = [0x59, 0x59, 0x23, 0x31, 0x04, 0x12, 0x26]
        initial = bytes([0]*4 + calendar + [0]*7)
        commands = [[58, *calendar[:n]] for n in range(7)]
        commands += [[58, *calendar, 0], *[[reg, 0] for reg in range(59, 65)]]
        for variant in ("WittyPi4", "WittyPi4_L3V7"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as d:
                directory = Path(d)
                binary = compile_rtc(directory, variant, WRITE_DEVICE)
                state = directory / "rtc-state"
                for command in commands:
                    with self.subTest(command=command):
                        state.write_bytes(initial)
                        subprocess.run([str(binary), "-y", "1",
                            f"w{len(command)}@0x08", *map(str, command)],
                            env={**os.environ, "RTC_STATE": str(state),
                                 "WRITE_TICK_AFTER": "0", "WRITE_NACK": "0"},
                            check=True, capture_output=True)
                        self.assertEqual(state.read_bytes(), initial)


if __name__ == "__main__":
    unittest.main()
