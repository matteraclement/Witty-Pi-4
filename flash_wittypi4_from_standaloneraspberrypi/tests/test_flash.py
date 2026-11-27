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


class FakeAvrdudeTestCase(unittest.TestCase):
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

    OLDER = BUNDLE.parent / "wp4-4.25-fw11-286a7d43c1b4"

    def staged_tree(self):
        # Mirror the programmer Pi layout: scripts, tools/ and bundles side by side.
        tree = self.root / "wp4"
        ignore = shutil.ignore_patterns("__pycache__", "tests")
        shutil.copytree(FLASH, tree / FLASH.name, ignore=ignore)
        shutil.copytree(FLASH.parent / "tools", tree / "tools", ignore=ignore)
        for bundle in (self.OLDER, BUNDLE):
            shutil.copytree(bundle, tree / "release" / bundle.name)
        return tree

    def run_staged(self, tree, name, *args):
        return subprocess.run(
            [str(tree / FLASH.name / name), *args],
            env=self.env, capture_output=True, text=True,
        )


class FlashScriptTests(FakeAvrdudeTestCase):
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


class UpdateFirmwareTests(FakeAvrdudeTestCase):
    """updatefirmware.sh resolves variant and bundle, then delegates to flash.sh."""

    def test_default_is_standard_board_with_newest_bundle(self):
        tree = self.staged_tree()
        result = self.run_staged(tree, "updatefirmware.sh", "-y")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.avrdude_args()
        self.assertEqual(args[args.index("-U") + 1], f"flash:w:{tree / 'release' / BUNDLE.name / 'WittyPi4.ino.hex'}:i")

    def test_mini_flag_selects_mini_image(self):
        tree = self.staged_tree()
        result = self.run_staged(tree, "updatefirmware.sh", "--mini", "-y")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.avrdude_args()
        self.assertEqual(args[args.index("-U") + 1], f"flash:w:{tree / 'release' / BUNDLE.name / 'WittyPi4_Mini.ino.hex'}:i")

    def test_explicit_release_dir_overrides_newest(self):
        result = self.run_script("updatefirmware.sh", "-y", "--l3v7", str(self.OLDER))
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.avrdude_args()
        self.assertEqual(args[args.index("-U") + 1], f"flash:w:{self.OLDER / 'WittyPi4_L3V7.ino.hex'}:i")

    def test_mini_still_needs_typed_confirmation(self):
        result = self.run_script("updatefirmware.sh", "--mini", str(BUNDLE), stdin="standard\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(self.avrdude_args())

    def test_conflicting_or_unknown_options_are_rejected(self):
        for args in (("--mini", "--l3v7"), ("--pico",), (str(BUNDLE), str(self.OLDER))):
            with self.subTest(args=args):
                result = self.run_script("updatefirmware.sh", "-y", *args)
                self.assertEqual(result.returncode, 2)
                self.assertIsNone(self.avrdude_args())


class CheckVariantTests(FakeAvrdudeTestCase):
    """check.sh --<variant> also compares the chip's flash with that variant's HEX, read-only."""

    def test_variant_flag_verifies_flash_without_writing(self):
        for variant, artifact in (("standard", "WittyPi4.ino.hex"), ("mini", "WittyPi4_Mini.ino.hex")):
            with self.subTest(variant=variant):
                result = self.run_script("check.sh", f"--{variant}", str(BUNDLE))
                self.assertEqual(result.returncode, 0, result.stderr)
                args = self.avrdude_args()
                self.assertEqual(args.count("-U"), 1)
                self.assertEqual(args[args.index("-U") + 1], f"flash:v:{BUNDLE / artifact}:i")
                self.assertNotIn("-e", args)

    def test_default_bundle_is_newest(self):
        tree = self.staged_tree()
        result = self.run_staged(tree, "check.sh", "--mini")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.avrdude_args()
        self.assertEqual(args[args.index("-U") + 1], f"flash:v:{tree / 'release' / BUNDLE.name / 'WittyPi4_Mini.ino.hex'}:i")

    def test_corrupt_image_is_never_compared(self):
        copy = self.root / BUNDLE.name
        shutil.copytree(BUNDLE, copy)
        hex_path = copy / "WittyPi4_Mini.ino.hex"
        hex_path.write_bytes(hex_path.read_bytes().replace(b":", b";", 1))
        result = self.run_script("check.sh", "--mini", str(copy))
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(self.avrdude_args())

    def test_bad_arguments_are_rejected(self):
        for args in ((str(BUNDLE),), ("--mini", "--l3v7"), ("--pico",), ("--mini", str(BUNDLE), str(self.OLDER))):
            with self.subTest(args=args):
                result = self.run_script("check.sh", *args)
                self.assertEqual(result.returncode, 2)
                self.assertIsNone(self.avrdude_args())


if __name__ == "__main__":
    unittest.main()
