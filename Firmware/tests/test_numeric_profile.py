"""Resource-saving arithmetic retains protection precision and RTC correction."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from test_firmware_handlers import ROOT, extract


PREFIX = r"""
#include <cassert>
#include <cstdint>
#include <cmath>
using byte=unsigned char;
byte i2cReg[50], skipAdjustRtcCount, lastOffset;
int adc;
char temperature;
int analogRead(byte) { return adc; }
char getTemperature() { return temperature; }
void writeToDevice(byte, byte, volatile byte* data, byte count) {
  assert(count==1); lastOffset=*data;
}
"""
SCENARIOS = r"""
int main() {
  for (adc=0;adc<1024;++adc) {
    for (uint16_t scale: {uint16_t(1100),uint16_t(22000),uint16_t(62700)}) {
      uint16_t measured=scaledAdc(0,scale);
      double exact=double(scale)*adc/1023;
      assert(measured<=exact && exact-measured<1.001);
    }
    for (int correction=-128;correction<128;++correction) {
      i2cReg[I2C_CONF_ADJ_VIN]=byte(correction);
      int16_t delta=getAdjustValue(I2C_CONF_ADJ_VIN);
      assert(delta==10*correction);
      uint16_t measured=adjusted(scaledAdc(0,62700),delta);
      int64_t exact=62700L*adc+int64_t(delta)*1023;
      for (int threshold=1;threshold<255;++threshold) {
        // Millivolt quantization never delays a low-voltage shutdown. Strict
        // greater-than recovery may be conservative by less than one mV.
        assert((measured<threshold*100)==(exact<int64_t(threshold)*100*1023));
        if (measured>threshold*100) assert(exact>int64_t(threshold)*100*1023);
      }
    }
  }
  for (int t=-128;t<128;++t) {
    char expected=0;
    if (t<26) expected=(t-26)*0.126728111f;
    else if (t>32 && t<=42) expected=(t-32)*-0.092165899f;
    else if (t>42) expected=-0.921658986f+(t-42)*-0.276497696f;
    for (int offset=0;offset<256;++offset) {
      i2cReg[I2C_CONF_RTC_ENABLE_TC]=1;
      i2cReg[I2C_CONF_RTC_OFFSET]=offset;
      skipAdjustRtcCount=254; temperature=t;
      adjustRTCIfNeeded();
      assert(lastOffset==value2Offset(offset2Value(offset)+expected));
    }
  }
}
"""


class NumericProfile(unittest.TestCase):
    def test_adc_thresholds_and_all_temperature_offsets(self):
        for variant in ("WittyPi4", "WittyPi4_L3V7"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as d:
                source = (ROOT / variant / (variant + ".ino")).read_text()
                defines = "\n".join(re.findall(
                    r"^#define (?:I2C_\w+|ADDRESS_\w+)\s+[^\n]+", source, re.MULTILINE))
                signatures = ("uint16_t adjusted(", "uint16_t scaledAdc(",
                    "int16_t getAdjustValue(", "char offset2Value(",
                    "byte value2Offset(", "void adjustRTCIfNeeded()")
                cpp = Path(d) / "numeric.cpp"
                cpp.write_text("#include <initializer_list>\n" + defines + "\n" + PREFIX +
                               "\n".join(extract(source, s) for s in signatures) + SCENARIOS)
                binary = Path(d) / "numeric"
                subprocess.run([*shlex.split(os.environ.get("CXX", "c++")), "-std=c++17",
                    "-fsigned-char", "-O2", "-Wall", "-Wextra", "-Werror", str(cpp),
                    "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
