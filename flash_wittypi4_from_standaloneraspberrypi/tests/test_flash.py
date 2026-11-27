"""Flash scripts against a fake avrdude: no GPIO, no hardware, no root."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

FLASH = Path(__file__).resolve().parents[1]
BUNDLE = FLASH.parent / "release" / "wp4-4.26-fw12-4f7c60d444d9"

FAKE_AVRDUDE = """#!/bin/bash
printf '%s\\n' "$@" > "$FAKE_AVRDUDE_LOG"
while [ "$#" -gt 0 ]; do
  [ "$1" = -C ] && cp "$2" "$FAKE_AVRDUDE_LOG.conf"
  shift
done
"""


class FlashScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        fake = self.root / "avrdude"
        fake.write_text(FAKE_AVRDUDE)
        fake.chmod(0o755)
        base = self.root / "base.conf"
        base.write_text("# base avrdude.conf\n")
        self.log = self.root / "avrdude.args"
        self.env = dict(
            os.environ,
            AVRDUDE_CMD=str(fake),
            AVRDUDE_BASE_CONF=str(base),
            FAKE_AVRDUDE_LOG=str(self.log),
        )

    def run_script(self, name, *args, stdin=""):
        return subprocess.run(
            [str(FLASH / name), *args],
            input=stdin, env=self.env, capture_output=True, text=True,
        )

    def avrdude_args(self):
        return self.log.read_text().splitlines() if self.log.exists() else None

    def test_check_never_writes(self):
        result = self.run_script("check.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.avrdude_args()
        self.assertEqual(args[args.index("-p") + 1], "attiny841")
        self.assertEqual(args[args.index("-c") + 1], "RasPi")
        self.assertNotIn("-U", args)
        self.assertNotIn("-e", args)

    def test_flash_writes_selected_variant_with_gpio_programmer(self):
        for variant, artifact in (("standard", "WittyPi4.ino.hex"), ("mini", "WittyPi4_Mini.ino.hex")):
            with self.subTest(variant=variant):
                result = self.run_script("flash.sh", "-y", str(BUNDLE), variant)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = self.avrdude_args()
                self.assertEqual(args[args.index("-U") + 1], f"flash:w:{BUNDLE / artifact}:i")
                self.assertEqual(args.count("-U"), 1)
                config = Path(str(self.log) + ".conf").read_text()
                self.assertIn("# base avrdude.conf", config)
                self.assertIn('id = "RasPi";', config)
                self.assertIn("reset = 12;", config)

    def test_corrupt_image_is_never_flashed(self):
        copy = self.root / BUNDLE.name
        shutil.copytree(BUNDLE, copy)
        hex_path = copy / "WittyPi4.ino.hex"
        hex_path.write_bytes(hex_path.read_bytes().replace(b":", b";", 1))
        result = self.run_script("flash.sh", "-y", str(copy), "standard")
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(self.avrdude_args())

    def test_unconfirmed_flash_is_refused(self):
        for reply in ("", "mini\n", "yes\n"):
            with self.subTest(reply=reply):
                result = self.run_script("flash.sh", str(BUNDLE), "standard", stdin=reply)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(self.avrdude_args())

    def test_typed_variant_confirms(self):
        result = self.run_script("flash.sh", str(BUNDLE), "standard", stdin="standard\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"flash:w:{BUNDLE / 'WittyPi4.ino.hex'}:i", self.avrdude_args())

    def test_unknown_variant_is_rejected(self):
        result = self.run_script("flash.sh", "-y", str(BUNDLE), "pico")
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(self.avrdude_args())


if __name__ == "__main__":
    unittest.main()
