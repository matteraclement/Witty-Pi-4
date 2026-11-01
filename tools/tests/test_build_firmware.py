"""Resource boundaries that must prevent publishing an oversized AVR build."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_firmware import _hex_bytes, _resource_usage, build_properties


class FirmwareBuildProperties(unittest.TestCase):
    def test_scheduled_profiles_keep_pinned_size_flags_for_every_variant(self):
        scheduled = (
            "-mcall-prologues -fno-inline-small-functions "
            "-fno-inline-functions-called-once -fno-tree-dominator-opts -finline-limit=3"
        )
        for variant in ("standard", "mini", "l3v7"):
            with self.subTest(variant=variant):
                cpp = scheduled + (" -DWITTY_PI_4_MINI" if variant == "mini" else "")
                self.assertEqual(build_properties(variant, True), [
                    "compiler.c.elf.extra_flags=-Wl,--relax",
                    "compiler.cpp.extra_flags=" + cpp,
                ])

    def test_historical_nonscheduled_profiles_keep_original_flags(self):
        for variant in ("standard", "mini", "l3v7"):
            with self.subTest(variant=variant):
                expected = ["compiler.c.elf.extra_flags=-Wl,--relax"]
                if variant == "mini":
                    expected.append("compiler.cpp.extra_flags=-DWITTY_PI_4_MINI")
                self.assertEqual(build_properties(variant, False), expected)


class FirmwareHexEncoding(unittest.TestCase):
    def test_objcopy_crlf_matches_git_lf_without_record_changes(self):
        committed = b":0400000001020304F2\n:00000001FF\n"
        compiler = b":0400000001020304F2\r\n:00000001FF\r\n"
        self.assertEqual(_hex_bytes(compiler), (committed, "CRLF"))
        self.assertEqual(_hex_bytes(committed), (committed, "LF"))

    def test_mixed_and_embedded_carriage_returns_are_rejected(self):
        for value in (b":0400000001020304F2\r\n:00000001FF\n",
                      b":040000000102\r0304F2\n:00000001FF\n"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                _hex_bytes(value)


class FirmwareResourceUsage(unittest.TestCase):
    def test_initialized_data_counts_in_flash_and_ram(self):
        output = """firmware.elf  :
section       size       addr
.text         8170          0
.data            4    8388704
.bss           218    8388708
.noinit          1    8388926
.comment        17          0
Total         8410
"""
        flash, ram, _ = _resource_usage(output)
        self.assertEqual((flash, ram), (8174, 223))

    def test_exact_device_limits_are_accepted(self):
        output = ".text 8188 0\n.data 4 8388704\n.bss 507 8388708\n.noinit 1 8389215\n"
        self.assertEqual(_resource_usage(output)[:2], (8192, 512))

    def test_each_capacity_overflow_is_rejected(self):
        for output in (
            ".text 8189 0\n.data 4 8388704\n.bss 1 8388708\n",
            ".text 8000 0\n.data 4 8388704\n.bss 508 8388708\n.noinit 1 8389216\n",
            ".text 8192 0\n.bootloader 1 8192\n.bss 1 8388704\n",
        ):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                _resource_usage(output)

    def test_missing_or_untrustworthy_section_sizes_are_rejected(self):
        for output in (
            "", ".data 4 8388704\n", ".text 0 0\n",
            ".text 100 0\n.text 100 100\n",
            ".text invalid 0\n", ".text 100 0\n.data -1 8388704\n",
        ):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                _resource_usage(output)


if __name__ == "__main__":
    unittest.main()
