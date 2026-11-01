"""Execute the production contract and GPIO handlers with a faulting EEPROM.

The AVR build and physical timing qualification remain separate gates.
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from test_firmware_handlers import ROOT, extract


class ShutdownContract(unittest.TestCase):
    def test_actual_handlers_and_torn_record_recovery(self):
        for variant in ("WittyPi4", "WittyPi4_L3V7"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as d:
                source = (ROOT / variant / (variant + ".ino")).read_text()
                defines = "\n".join(re.findall(
                    r"^#define (?:PIN_(?:SYS_UP|BUTTON|CTRL|TX_UP)|I2C_\w+|REASON_\w+|ADDRESS_\w+)\s+[^\n]+",
                    source, re.MULTILINE))
                signatures = (
                    "byte bcd2dec(", "uint32_t getTimestamp(",
                    "void cutPower()", "void emulateButtonClick()",
                    "unsigned int getPowerCutPreloadTimer(",
                    "void forcePowerCutIfNeeded()", "void turnOffIfPowerOn()",
                    "void turnOnIfPowerOff()", "void handleTemperatureActtonsIfNeeded()",
                    "ISR (PCINT0_vect)", "ISR (PCINT1_vect)", "ISR (TIM1_OVF_vect)",
                )
                bodies = "\n".join(extract(source, name) for name in signatures)
                harness = (ROOT / "tests" / "shutdown_contract.cpp").read_text()
                prefix, scenarios = harness.split("// PRODUCTION HERE")
                cpp = Path(d) / "contract.cpp"
                cpp.write_text(defines + "\n" + prefix + bodies +
                    f'\n#include "{ROOT / variant / "ScheduledContract.h"}"\n' + scenarios)
                binary = Path(d) / "contract"
                subprocess.run([
                    *shlex.split(os.environ.get("CXX", "c++")), "-std=c++17", "-fsigned-char",
                    "-O2", "-Wall", "-Wextra", "-Werror", str(cpp), "-o", str(binary),
                ], check=True)
                subprocess.run([str(binary)], check=True)



if __name__ == "__main__":
    unittest.main()
