"""Offline actual-sketch handler tests; requires Python 3 and a C++17 compiler.

Run: python3 -m unittest discover -s Witty-Pi-4/Firmware/tests -v
CXX may select g++ or clang++. No board access or retained evidence writes.
The unchanged handler bodies are compiled with discrete-event Arduino stubs;
this is not AVR timing, interrupt-preemption or electrical qualification.
"""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def extract(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


STUBS = r"""
#include <cassert>
#include <iostream>
using byte = unsigned char;
using boolean = bool;
#define ISR(name) void name()
constexpr int INPUT_PULLUP=2, OUTPUT=1;
bool powerIsOn, listenToTxd, systemIsUp, turningOff, turnOffFromTXD;
bool buttonPressed, isButtonClickEmulated, wakeupByWatchdog, ledIsOn;
byte lastButton, lastSystemUp, alarm1Delayed;
byte i2cReg[256];
unsigned int powerCutDelay, TCNT1, skipTempShutdownCount;
unsigned int skipLowVoltageDetectCount;
byte lowVoltageCacheInteger, lowVoltageCacheDecimal;
int pins[12], modes[12], sleepCount;
float voltage;
char temperature;
int digitalRead(int pin) { return pins[pin]; }
void digitalWrite(int pin, int value) {
  // An input pull-up does not override an externally held switch.
  if (pin != PIN_BUTTON || modes[pin] == OUTPUT) pins[pin] = value;
}
void pinMode(int pin, int mode) { modes[pin] = mode; }
void ledOn() { ledIsOn=true; }
void ledOff() { ledIsOn=false; }
void powerOn() { powerIsOn=true; pins[PIN_CTRL]=1; }
void sleep() { ++sleepCount; } // Stop at sleep entry, before any future wake.
void updateRegister(byte reg, byte value) { i2cReg[reg]=value; }
float getInputVoltage() { return voltage; }
char getTemperature() { return temperature; }
bool canTriggerAlarm() { return true; }
void reset_rtc_alarm() {}
void copyAlarm(byte) {}
// RTC fixture: day 1, 00:00:10.
struct RtcBuffer {
  byte index;
  byte read() {
    byte reg=index++;
    if (reg == I2C_RTC_SECONDS-I2C_RTC_CTRL1) return 0x10;
    if (reg == I2C_RTC_DAYS-I2C_RTC_CTRL1) return 1;
    return 0;
  }
} softWireMaster;
byte readFromDevice(byte, byte index, byte count) {
  softWireMaster.index=index;
  return count;
}
void writeToDevice(byte, byte, byte*, byte) {}
struct Eeprom {
  byte read(byte index) { return index == I2C_FW_REVISION ? 8 : 255; }
  void update(byte, byte) {}
} EEPROM;
"""

SCENARIOS = r"""
void coldBootReady() {
  powerIsOn=true; listenToTxd=true; systemIsUp=true; turningOff=false;
  turnOffFromTXD=false; buttonPressed=false; isButtonClickEmulated=false;
  wakeupByWatchdog=false; ledIsOn=false; powerCutDelay=0; sleepCount=0;
  lastButton=1; lastSystemUp=0; alarm1Delayed=0;
  skipTempShutdownCount=120; skipLowVoltageDetectCount=180;
  lowVoltageCacheInteger=lowVoltageCacheDecimal=0;
  voltage=3.0f; temperature=90;
  for (int &v : pins) v=0;
  for (int &v : modes) v=INPUT_PULLUP;
  for (byte &v : i2cReg) v=0;
  initializeRegisters();
  assert(i2cReg[I2C_ID] == EXPECTED_ID);
  assert(i2cReg[I2C_FW_REVISION] >= 9); // Upgrade must not restore old EEPROM capabilities.
  pins[PIN_CTRL]=pins[PIN_TX_UP]=pins[PIN_BUTTON]=1;
}
void shortPress() {
  pins[PIN_BUTTON]=0; PCINT1_vect();
  pins[PIN_BUTTON]=1; PCINT1_vect();
}
void finishEmulatedClick() {
  assert(isButtonClickEmulated && pins[PIN_BUTTON] == 0);
  PCINT1_vect();
  pins[PIN_BUTTON]=1; PCINT1_vect();
}
void txd(int level) { pins[PIN_TX_UP]=level; PCINT0_vect(); }
void sysUp() {
  ledOff(); // Watchdog clears reboot LED before daemon's SYS_UP pulse.
  pins[PIN_SYS_UP]=1; PCINT1_vect();
  pins[PIN_SYS_UP]=0; PCINT1_vect();
  assert(systemIsUp);
}
void softwareReboot() {
  txd(0);
  assert(turningOff && turnOffFromTXD && !systemIsUp);
  txd(1); TIM1_OVF_vect();
  assert(powerIsOn && !turningOff && !turnOffFromTXD && sleepCount == 0);
  assert(i2cReg[I2C_ACTION_REASON] == REASON_REBOOT);
}
void expectCut() {
  TIM1_OVF_vect();
  assert(!powerIsOn && pins[PIN_CTRL] == 0 && !turnOffFromTXD);
  assert(sleepCount == 1);
}
int main() {
  coldBootReady(); shortPress(); expectCut();

  coldBootReady(); softwareReboot();
  TIM1_OVF_vect();
  assert(powerIsOn && sleepCount == 0); // Genuine reboot is not a shutdown.
  sysUp(); shortPress();
  assert(turningOff && !turnOffFromTXD && !systemIsUp);
  expectCut(); // TXD remains HIGH, as with slow Linux shutdown.
  txd(0); TIM1_OVF_vect();
  assert(!powerIsOn && !turnOffFromTXD); // Late TXD cannot revive power.

  coldBootReady(); softwareReboot(); sysUp();
  txd(0); assert(turnOffFromTXD && turningOff); expectCut();
  coldBootReady(); softwareReboot(); sysUp(); softwareReboot(); sysUp();
  assert(powerIsOn); // A subsequent genuine reboot is still recognized.
  shortPress(); txd(0); expectCut(); // Linux halts before cut deadline.

  coldBootReady(); softwareReboot(); sysUp();
  i2cReg[I2C_CONF_OVER_TEMP_ACTION]=1;
  handleTemperatureActtonsIfNeeded();
  assert(turningOff && !turnOffFromTXD);
  finishEmulatedClick(); expectCut();

  coldBootReady(); softwareReboot(); sysUp(); temperature=0;
  i2cReg[I2C_CONF_BELOW_TEMP_ACTION]=1;
  handleTemperatureActtonsIfNeeded();
  assert(turningOff && !turnOffFromTXD);
  finishEmulatedClick(); expectCut();

  coldBootReady(); softwareReboot(); sysUp();
  i2cReg[I2C_CONF_DAY_ALARM2]=1;
  i2cReg[I2C_CONF_SECOND_ALARM2]=0x10;
  processAlarmIfNeeded();
  assert(turningOff && !turnOffFromTXD);
  finishEmulatedClick(); expectCut();

  coldBootReady(); softwareReboot(); sysUp();
  i2cReg[I2C_POWER_MODE]=1; i2cReg[I2C_CONF_LOW_VOLTAGE]=35;
#ifdef L3V7
  assert(detectLowVoltage() == 1);
#else
  processLowVoltageIfNeeded();
#endif
  finishEmulatedClick();
  assert(turningOff && !turnOffFromTXD);
  expectCut();

  coldBootReady(); txd(0); cutPower();
  assert(!powerIsOn && !turnOffFromTXD); // Includes L3V7's direct cut path.

  coldBootReady(); softwareReboot(); // Force cut works even without SYS_UP.
  pins[PIN_BUTTON]=0; PCINT1_vect(); expectCut();

  coldBootReady(); i2cReg[I2C_CONF_POWER_CUT_DELAY]=250;
  shortPress();
  assert(powerCutDelay == 167);
  TIM1_OVF_vect(); assert(powerIsOn && powerCutDelay == 84);
  TIM1_OVF_vect(); assert(powerIsOn && powerCutDelay == 1);
  TIM1_OVF_vect(); assert(powerIsOn && powerCutDelay == 0);
  expectCut(); // 25-second host mitigation is not shortened.

  coldBootReady(); i2cReg[I2C_CONF_POWER_CUT_DELAY]=250;
  pins[PIN_BUTTON]=0; PCINT1_vect(); expectCut(); // Held-button force cut.
  std::cout << "PASS: actual handlers, identity " << EXPECTED_ID << "\n";
}
"""


class FirmwareHandlers(unittest.TestCase):
    def run_sketch(self, name, product_id, *flags):
        source = (ROOT / name / (name + ".ino")).read_text()
        # Use production constants, not a second protocol/register mapping.
        defines = "\n".join(re.findall(
            r"^#define (?:PIN_(?:SYS_UP|BUTTON|CTRL|TX_UP)|I2C_\w+|REASON_\w+|ADDRESS_\w+)\s+[^\n]+",
            source, re.MULTILINE,
        ))
        signatures = [
            "void initializeRegisters()", "void cutPower()",
            "void forcePowerCutIfNeeded()", "void emulateButtonClick()",
            "unsigned int getPowerCutPreloadTimer(boolean reset)",
            "ISR (PCINT0_vect)", "ISR (PCINT1_vect)", "ISR (TIM1_OVF_vect)",
            "byte bcd2dec(byte bcd)",
            "long getTimestamp(byte date, byte hours, byte minutes, byte seconds)",
            "void turnOffIfPowerOn()", "void turnOnIfPowerOff()",
            "void handleTemperatureActtonsIfNeeded()", "void processAlarmIfNeeded()",
            "byte detectLowVoltage()" if name.endswith("L3V7")
            else "void processLowVoltageIfNeeded()",
        ]
        handlers = "\n\n".join(extract(source, signature) for signature in signatures)
        with tempfile.TemporaryDirectory(prefix="wp4-handlers-") as directory:
            cpp = Path(directory) / "handlers.cpp"
            binary = Path(directory) / "handlers"
            cpp.write_text(defines + "\n" + STUBS + handlers + SCENARIOS)
            subprocess.run([
                *shlex.split(os.environ.get("CXX", "c++")), "-std=c++17",
                "-Wall", "-Wextra", "-Werror", f"-DEXPECTED_ID={product_id}",
                *flags, str(cpp), "-o", str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)

    def test_wittypi4(self):
        self.run_sketch("WittyPi4", 0x26)

    def test_wittypi4_mini(self):
        self.run_sketch("WittyPi4", 0x36, "-DWITTY_PI_4_MINI")

    def test_wittypi4_l3v7(self):
        self.run_sketch("WittyPi4_L3V7", 0x37, "-DL3V7")


if __name__ == "__main__":
    unittest.main()
