"""Release consumer boundaries; fixtures are disposable Git repositories."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release


def hex_record(address, kind, payload=b""):
    body = bytes([len(payload), address >> 8, address & 255, kind]) + payload
    return b":" + (body + bytes([-sum(body) & 255])).hex().upper().encode() + b"\n"


def image(payload=b"\x01\x02\x03\x04"):
    return hex_record(0, 0, payload) + hex_record(0, 1)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repository"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Release Test")
        self.git("config", "user.email", "release@example.invalid")
        self.git("config", "core.fileMode", "true")
        self.files = {
            "README.md": b"Upstream fixture\n",
            "LICENSE": b"Fixture license\n",
            "Software/install.sh": b"#!/bin/sh\nexit 0\n",
            "Software/wittypi/utilities.sh": b"SOFTWARE_VERSION='4.23'\n",
            "Software/wittypi/daemon.sh": b"#!/bin/sh\necho committed\n",
            "Firmware/tests/fixture.txt": b"committed test input\n",
        }
        for path in release.SKETCHES:
            self.files[path] = b"void setup() {\n  i2cReg[I2C_FW_REVISION] = 0x09;\n}\n"
        for _, _, path in release.VARIANTS:
            self.files[path] = image()
        for name, data in self.files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o755 if name.endswith(".sh") else 0o644)
        self.commit = self.commit_files()
        self.output = self.root / "releases"

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.STDOUT).decode().strip()

    def commit_files(self):
        self.git("add", ".")
        self.git("commit", "-qm", "Committed fixture")
        return self.git("rev-parse", "HEAD")

    def create(self, **kwargs):
        return release.create_release(self.repo, self.commit, kwargs.pop("profile", "atomic-rev9"),
                                      kwargs.pop("output", self.output), **kwargs)

    def resign(self, bundle, manifest=None):
        """Refresh checksums to exercise coherence beyond accidental corruption."""
        if manifest is None:
            manifest = json.loads((bundle / "release-manifest.json").read_bytes())
        for name in manifest["artifacts"]:
            manifest["artifacts"][name] = release.describe((bundle / name).read_bytes())
        (bundle / "release-manifest.json").write_bytes(release.json_bytes(manifest))
        (bundle / "SHA256SUMS").write_text("".join(
            f"{release.sha256(path.read_bytes())}  {path.name}\n"
            for path in sorted(bundle.iterdir()) if path.name != "SHA256SUMS"), encoding="ascii")

    def replace_source(self, bundle, path, data):
        files = release.read_archive(bundle / "source.tar.gz")
        files[path] = (files[path][0], data)
        release.write_archive(bundle / "source.tar.gz", files, 0)
        manifest = json.loads((bundle / "release-manifest.json").read_bytes())
        manifest["source"]["files"][path]["git_blob"] = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        self.resign(bundle, manifest)

    def commit_scheduled_profile(self, revision=11, version="4.25"):
        (self.repo / "Software/wittypi/utilities.sh").write_text(
            f"SOFTWARE_VERSION='{version}'\n")
        for sketch in release.SKETCHES:
            (self.repo / sketch).write_text(
                f"void setup() {{\n  i2cReg[I2C_FW_REVISION] = 0x{revision:02x};\n}}\n")
            (self.repo / Path(sketch).parent / "ScheduledContract.h").write_text(
                "// Scheduled contract fixture, not production firmware.\n")
        self.commit = self.commit_files()

    def synthetic_build(self, source, output, cli):
        """Exercise publication with deterministic fixtures, not a claimed AVR build."""
        receipt = {
            "schema_version": 1, "status": "verified-build", "fqbn": release.BUILD_FQBN,
            "toolchain": {
                "arduino_cli": {"version": "fixture"},
                "core": {"id": "ATTinyCore:avr", "version": "1.5.2"},
                "avr_gcc": {"version": "7.3.0-atmel3.6.1-arduino7",
                            "compiler_version": "avr-gcc 7.3.0"},
            },
            "variants": [],
        }
        for name, product, path in release.VARIANTS:
            artifact = (source / path).read_bytes()
            filename = Path(path).name
            (output / filename).write_bytes(artifact)
            properties = release.build_properties(
                name, (source / Path(path).parent / "ScheduledContract.h").is_file())
            command = [cli, "compile", "--fqbn", release.BUILD_FQBN,
                       "--clean", "--build-path", "/fixture/build/" + name]
            for value in properties:
                command.extend(["--build-property", value])
            command.append("/fixture/source/" + str(Path(path).parent))
            receipt["variants"].append({
                "name": name, "product_id": product, "sketch": str(Path(path).parent),
                "hex_file": filename, **release.describe(artifact),
                "compiler_hex_sha256": release.sha256(artifact),
                "compiler_hex_size_bytes": len(artifact),
                "compiler_hex_line_endings": "LF", "artifact_hex_line_endings": "LF",
                "flash_bytes": release.intel_hex(artifact)["data_bytes"],
                "flash_capacity_bytes": 8192, "static_ram_bytes": 100,
                "ram_capacity_bytes": 512, "command": command,
                "build_properties": properties,
            })
        return receipt

    def test_retained_profile_rebuild_publication_is_deterministic_and_committed_only(self):
        self.commit_scheduled_profile()
        with patch("build_firmware.build_firmware", side_effect=self.synthetic_build):
            first = self.create(profile="scheduled-rev11", rebuild=True)
            # Even revision/version/HEX edits cannot change the committed snapshot.
            (self.repo / release.SKETCHES[0]).write_bytes(b"dirty sketch\n")
            (self.repo / "Software/wittypi/utilities.sh").write_bytes(b"dirty version\n")
            (self.repo / release.VARIANTS[0][2]).write_bytes(b"dirty HEX\n")
            second = self.create(profile="scheduled-rev11", rebuild=True,
                                 output=self.root / "second")
        self.assertEqual({p.name: p.read_bytes() for p in first.iterdir()},
                         {p.name: p.read_bytes() for p in second.iterdir()})
        manifest = release.verify_bundle(first)
        self.assertEqual(manifest["release_name"], f"wp4-4.25-fw11-{self.commit[:12]}")
        self.assertEqual(manifest["software_version"], "4.25")
        self.assertEqual(manifest["compatibility"], release.PROFILES["scheduled-rev11"])
        self.assertEqual(manifest["compatibility"]["nominal_revision"], 11)
        self.assertEqual(manifest["compatibility"]["rtc_trust"],
                         "readonly register 74; 0=untrusted, 1=trusted; retained across reset")
        self.assertEqual(manifest["compatibility"]["rtc_trust_retention"],
                         "PCF85063A RAM 0x03; 0x00=pending, 0xa5=clean; verified pending before mutation; trusted only after STOP/frozen readback/run-valid verification")
        self.assertEqual(manifest["compatibility"]["rtc_trust_raw_access"],
                         "virtual register 57 writes rejected")
        self.assertEqual(manifest["compatibility"]["rtc_calendar_command"],
                         "register 58, w8@0x08 (unchanged)")
        self.assertEqual(manifest["compatibility"]["shutdown_contract"],
                         release.PROFILES["scheduled-rev10"]["shutdown_contract"])
        self.assertEqual(manifest["provenance"]["build"], "rebuilt-byte-identical")
        receipt = release.load_json(first / "build-verification.json")
        self.assertEqual(len(receipt["variants"]), 3)
        for variant in receipt["variants"]:
            self.assertEqual(variant["build_properties"],
                             release.build_properties(variant["name"], True))

    def test_retained_profile_cannot_be_published_without_rebuild(self):
        self.commit_scheduled_profile()
        with self.assertRaisesRegex(release.ReleaseError, "requires a byte-identical rebuild"):
            self.create(profile="scheduled-rev11")
        self.assertFalse(self.output.exists())

    def test_retained_profile_cannot_claim_archived_provenance(self):
        self.commit_scheduled_profile()
        with patch("build_firmware.build_firmware", side_effect=self.synthetic_build):
            bundle = self.create(profile="scheduled-rev11", rebuild=True)
        manifest = release.load_json(bundle / "release-manifest.json")
        manifest["provenance"]["build"] = "archived-not-rebuilt"
        del manifest["artifacts"]["build-verification.json"]
        (bundle / "build-verification.json").unlink()
        self.resign(bundle, manifest)
        with self.assertRaisesRegex(release.ReleaseError, "requires a byte-identical rebuild"):
            release.verify_bundle(bundle)

    def test_retained_profile_requires_software_425_and_both_revision_11_sketches(self):
        self.commit_scheduled_profile(version="4.24")
        with self.assertRaisesRegex(release.ReleaseError, "requires software 4.25"):
            self.create(profile="scheduled-rev11", rebuild=True)
        self.commit_scheduled_profile(revision=10)
        with self.assertRaisesRegex(release.ReleaseError, "revision"):
            self.create(profile="scheduled-rev11", rebuild=True)
        self.commit_scheduled_profile()
        (self.repo / release.SKETCHES[1]).write_text("i2cReg[I2C_FW_REVISION] = 0x0a;\n")
        self.commit = self.commit_files()
        with self.assertRaisesRegex(release.ReleaseError, "revision"):
            self.create(profile="scheduled-rev11", rebuild=True)
        self.assertFalse(self.output.exists())

    def test_retained_profile_rejects_weakened_trust_metadata(self):
        self.commit_scheduled_profile()
        with patch("build_firmware.build_firmware", side_effect=self.synthetic_build):
            bundle = self.create(profile="scheduled-rev11", rebuild=True)
        manifest = release.load_json(bundle / "release-manifest.json")
        manifest["compatibility"]["rtc_trust"] = "volatile trust"
        self.resign(bundle, manifest)
        with self.assertRaisesRegex(release.ReleaseError, "profile metadata"):
            release.verify_bundle(bundle)

    def test_retained_profile_rejects_historical_build_flags(self):
        self.commit_scheduled_profile()
        with patch("build_firmware.build_firmware", side_effect=self.synthetic_build):
            bundle = self.create(profile="scheduled-rev11", rebuild=True)
        receipt_path = bundle / "build-verification.json"
        receipt = release.load_json(receipt_path)
        receipt["variants"][0]["build_properties"] = release.build_properties("standard", False)
        receipt_path.write_bytes(release.json_bytes(receipt))
        self.resign(bundle)
        with self.assertRaisesRegex(release.ReleaseError, "Wrong build properties"):
            release.verify_bundle(bundle)

    def test_retained_profile_rebuilt_mismatch_never_publishes(self):
        self.commit_scheduled_profile()

        def mismatch(source, output, cli):
            receipt = self.synthetic_build(source, output, cli)
            (output / "WittyPi4_Mini.ino.hex").write_bytes(image(b"\x09\x08\x07\x06"))
            return receipt

        with patch("build_firmware.build_firmware", side_effect=mismatch):
            with self.assertRaisesRegex(release.ReleaseError, "differs from committed HEX"):
                self.create(profile="scheduled-rev11", rebuild=True)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_historical_scheduled_profile_still_archives_and_rebuilds(self):
        self.commit_scheduled_profile(revision=10, version="4.24")
        archived = self.create(profile="scheduled-rev10")
        self.assertEqual(release.verify_bundle(archived)["provenance"]["build"],
                         "archived-not-rebuilt")
        with patch("build_firmware.build_firmware", side_effect=self.synthetic_build):
            rebuilt = self.create(profile="scheduled-rev10", rebuild=True,
                                  output=self.root / "rebuilt")
        manifest = release.verify_bundle(rebuilt)
        self.assertEqual(manifest["provenance"]["build"], "rebuilt-byte-identical")
        self.assertEqual(manifest["software_version"], "4.24")
        self.assertNotIn("rtc_trust", manifest["compatibility"])

    def test_revision_12_profile_requires_software_426_and_rebuild(self):
        self.commit_scheduled_profile(revision=12, version="4.26")
        with self.assertRaisesRegex(release.ReleaseError, "requires a byte-identical rebuild"):
            self.create(profile="scheduled-rev12")
        with patch("build_firmware.build_firmware", side_effect=self.synthetic_build):
            manifest = release.verify_bundle(self.create(profile="scheduled-rev12", rebuild=True))
        self.assertEqual(manifest["release_name"], f"wp4-4.26-fw12-{self.commit[:12]}")
        self.assertEqual(manifest["compatibility"]["nominal_revision"], 12)
        self.assertEqual(manifest["compatibility"]["rtc_trust"],
                         release.PROFILES["scheduled-rev11"]["rtc_trust"])
        self.assertIn("temperature_read_failure", manifest["compatibility"])
        self.commit_scheduled_profile(revision=12, version="4.25")
        with self.assertRaisesRegex(release.ReleaseError, "requires software 4.26"):
            self.create(profile="scheduled-rev12", rebuild=True, output=self.root / "old-software")
        self.commit_scheduled_profile(revision=11, version="4.26")
        with self.assertRaisesRegex(release.ReleaseError, "revision"):
            self.create(profile="scheduled-rev12", rebuild=True, output=self.root / "old-firmware")

    def test_changed_firmware_or_software_needs_new_revision_or_version(self):
        published = self.repo / "release"
        self.commit_scheduled_profile(revision=12, version="4.26")
        with patch("build_firmware.build_firmware", side_effect=self.synthetic_build):
            self.create(profile="scheduled-rev12", rebuild=True, output=published)
            # Identical firmware and software may be republished from a later commit.
            (self.repo / "README.md").write_text("Documentation-only change\n")
            self.commit = self.commit_files()
            self.create(profile="scheduled-rev12", rebuild=True, output=self.root / "docs")
            changes = (
                (release.VARIANTS[1][2], image(b"\x05\x06\x07\x08"), "bump I2C_FW_REVISION"),
                ("Software/wittypi/daemon.sh", "#!/bin/sh\necho changed\n", "bump SOFTWARE_VERSION"),
            )
            for path, content, message in changes:
                with self.subTest(path=path):
                    original = (self.repo / path).read_bytes()
                    target = self.repo / path
                    if isinstance(content, bytes):
                        target.write_bytes(content)
                    else:
                        target.write_text(content)
                    self.commit = self.commit_files()
                    # The repository's published bundles count for any output root.
                    output = self.root / ("changed-" + Path(path).name)
                    with self.assertRaisesRegex(release.ReleaseError, message):
                        self.create(profile="scheduled-rev12", rebuild=True, output=output)
                    self.assertFalse(output.exists())
                    target.write_bytes(original)
                    self.commit = self.commit_files()

    def test_historical_unpinned_software_version_does_not_block_reexport(self):
        # Revision-7/9 bundles share software 4.23 with different trees.
        self.create(output=self.repo / "release")
        (self.repo / "Software/wittypi/daemon.sh").write_text("#!/bin/sh\necho other\n")
        self.commit = self.commit_files()
        self.create(output=self.root / "reexport")

    def test_export_is_deterministic_and_ignores_dirty_worktree(self):
        first = self.create()
        first_bytes = {path.name: path.read_bytes() for path in first.iterdir()}
        (self.repo / "Software/wittypi/daemon.sh").write_bytes(b"dirty host software\n")
        (self.repo / release.SKETCHES[0]).write_bytes(b"dirty firmware\n")
        (self.repo / release.VARIANTS[0][2]).write_bytes(b"invalid modified HEX\n")
        (self.repo / "Firmware/generated.lst").write_bytes(b"untracked output\n")
        second = self.create(output=self.root / "another-output")
        self.assertEqual(first_bytes, {path.name: path.read_bytes() for path in second.iterdir()})
        snapshot = release.read_archive(second / "source.tar.gz")
        self.assertEqual(set(snapshot), set(self.files))
        self.assertEqual(snapshot["Software/wittypi/daemon.sh"], (0o755, self.files["Software/wittypi/daemon.sh"]))
        self.assertEqual(snapshot[release.SKETCHES[0]][0], 0o644)
        manifest = release.verify_bundle(second)
        self.assertEqual(manifest["source"]["commit"], self.commit)
        self.assertEqual(manifest["provenance"]["build"], "archived-not-rebuilt")
        self.assertFalse((second / "build-verification.json").exists())

    def test_copied_bundle_verifies_without_repository_or_external_programs(self):
        original = self.create()
        copied = self.root / "standalone-copy"
        shutil.copytree(original, copied)
        shutil.rmtree(self.repo)
        result = subprocess.run([sys.executable, release.__file__, "verify", str(copied)],
                                env=dict(os.environ, PATH=""), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_release_is_never_overwritten(self):
        bundle = self.create()
        before = {path.name: path.read_bytes() for path in bundle.iterdir()}
        with self.assertRaisesRegex(release.ReleaseError, "already exists"):
            self.create()
        self.assertEqual(before, {path.name: path.read_bytes() for path in bundle.iterdir()})
        self.assertEqual(list(self.output.iterdir()), [bundle])

    def test_existing_empty_directory_and_dangling_symlink_are_not_replaced(self):
        name = f"wp4-4.23-fw9-{self.commit[:12]}"
        self.output.mkdir()
        target = self.output / name
        target.mkdir()
        with self.assertRaisesRegex(release.ReleaseError, "already exists"):
            self.create()
        self.assertEqual(list(target.iterdir()), [])
        target.rmdir()
        target.symlink_to(self.root / "absent")
        with self.assertRaisesRegex(release.ReleaseError, "already exists"):
            self.create()
        self.assertTrue(target.is_symlink())

    def test_wrong_profile_or_disagreeing_sketch_revision_rejected(self):
        with self.assertRaisesRegex(release.ReleaseError, "revision"):
            self.create(profile="legacy-rev7")
        path = self.repo / release.SKETCHES[1]
        path.write_bytes(path.read_bytes().replace(b"0x09", b"0x07"))
        self.commit = self.commit_files()
        with self.assertRaisesRegex(release.ReleaseError, "revision"):
            self.create()
        self.assertFalse(self.output.exists())

    def test_legacy_profile_is_archived_without_rebuild(self):
        for name in release.SKETCHES:
            path = self.repo / name
            path.write_bytes(path.read_bytes().replace(b"0x09", b"0x07"))
        self.commit = self.commit_files()
        bundle = self.create(profile="legacy-rev7")
        self.assertEqual(release.verify_bundle(bundle)["compatibility"]["revision_source"], "EEPROM-overridable")
        with self.assertRaisesRegex(release.ReleaseError, "without rebuilding"):
            self.create(profile="legacy-rev7", rebuild=True, output=self.root / "rebuild")
        self.assertFalse((self.root / "rebuild").exists())

    def test_invalid_committed_hex_fails_before_publication(self):
        (self.repo / release.VARIANTS[0][2]).write_bytes(b":00000001FE\n")
        self.commit = self.commit_files()
        with self.assertRaisesRegex(release.ReleaseError, "HEX"):
            self.create()
        self.assertFalse(self.output.exists())

    def test_symlink_in_committed_source_is_rejected(self):
        (self.repo / "Software/wittypi/link").symlink_to("utilities.sh")
        self.commit = self.commit_files()
        with self.assertRaisesRegex(release.ReleaseError, "regular committed"):
            self.create()
        self.assertFalse(self.output.exists())

    def test_hash_corruption_and_extra_or_missing_files_are_rejected(self):
        bundle = self.create()
        firmware = bundle / "WittyPi4.ino.hex"
        original = firmware.read_bytes()
        firmware.write_bytes(image(b"\x05\x06\x07\x08"))
        with self.assertRaisesRegex(release.ReleaseError, "hash/size"):
            release.verify_bundle(bundle)
        firmware.write_bytes(original)
        extra = bundle / "unexpected"
        extra.write_bytes(b"extra")
        with self.assertRaisesRegex(release.ReleaseError, "bundle files"):
            release.verify_bundle(bundle)
        extra.unlink()
        firmware.unlink()
        with self.assertRaisesRegex(release.ReleaseError, "bundle files"):
            release.verify_bundle(bundle)

    def test_self_consistent_checksums_cannot_hide_firmware_source_mismatch(self):
        bundle = self.create()
        (bundle / "WittyPi4.ino.hex").write_bytes(image(b"\x05\x06\x07\x08"))
        self.resign(bundle)
        with self.assertRaisesRegex(release.ReleaseError, "Firmware/source mismatch"):
            release.verify_bundle(bundle)

    def test_source_change_without_matching_git_blob_is_rejected(self):
        bundle = self.create()
        files = release.read_archive(bundle / "source.tar.gz")
        files["README.md"] = (0o644, b"different source\n")
        release.write_archive(bundle / "source.tar.gz", files, 0)
        self.resign(bundle)
        with self.assertRaisesRegex(release.ReleaseError, "Git blob/mode"):
            release.verify_bundle(bundle)

    def test_source_version_and_revision_must_match_manifest(self):
        for path, content, message in (
            ("Software/wittypi/utilities.sh", b"SOFTWARE_VERSION='4.24'\n", "Software version"),
            (release.SKETCHES[0], b"i2cReg[I2C_FW_REVISION] = 0x07;\n", "revision"),
        ):
            with self.subTest(path=path):
                bundle = self.create(output=self.root / message.replace(" ", "-"))
                self.replace_source(bundle, path, content)
                with self.assertRaisesRegex(release.ReleaseError, message):
                    release.verify_bundle(bundle)

    def test_software_archive_must_match_source_bytes_and_modes(self):
        bundle = self.create()
        archive = bundle / "wittypi-software.tar.gz"
        files = release.read_archive(archive)
        files["wittypi/daemon.sh"] = (0o644, self.files["Software/wittypi/daemon.sh"])
        release.write_archive(archive, files, 0)
        self.resign(bundle)
        with self.assertRaisesRegex(release.ReleaseError, "Software archive/source"):
            release.verify_bundle(bundle)

    def test_license_must_match_source(self):
        bundle = self.create()
        (bundle / "LICENSE").write_bytes(b"replaced license\n")
        self.resign(bundle)
        with self.assertRaisesRegex(release.ReleaseError, "LICENSE/source"):
            release.verify_bundle(bundle)

    def test_unsafe_archive_members_are_rejected_even_with_matching_checksums(self):
        cases = (("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                 ("wittypi/link", tarfile.SYMTYPE), ("wittypi/hard", tarfile.LNKTYPE),
                 ("wittypi/pipe", tarfile.FIFOTYPE))
        for index, (name, kind) in enumerate(cases):
            with self.subTest(name=name):
                bundle = self.create(output=self.root / f"unsafe-{index}")
                with tarfile.open(bundle / "wittypi-software.tar.gz", "w:gz") as archive:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.mode = 0o644
                    member.linkname = "../../outside" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
                    archive.addfile(member, io.BytesIO())
                self.resign(bundle)
                with self.assertRaises(release.ReleaseError):
                    release.verify_bundle(bundle)
        self.assertFalse((self.root / "escape").exists())

    def test_duplicate_archive_members_are_rejected(self):
        bundle = self.create()
        with tarfile.open(bundle / "wittypi-software.tar.gz", "w:gz") as archive:
            for _ in range(2):
                member = tarfile.TarInfo("wittypi/duplicate")
                member.mode = 0o644
                archive.addfile(member, io.BytesIO())
        self.resign(bundle)
        with self.assertRaisesRegex(release.ReleaseError, "Duplicate archive"):
            release.verify_bundle(bundle)

    def test_manifest_cannot_reference_paths_outside_bundle(self):
        bundle = self.create()
        manifest = json.loads((bundle / "release-manifest.json").read_bytes())
        manifest["artifacts"]["../outside"] = {"sha256": "0" * 64, "size_bytes": 0}
        (bundle / "release-manifest.json").write_bytes(release.json_bytes(manifest))
        with self.assertRaisesRegex(release.ReleaseError, "Unsafe artifact path"):
            release.verify_bundle(bundle)

    def test_bundle_symlink_is_rejected(self):
        bundle = self.create()
        license_file = bundle / "LICENSE"
        license_file.unlink()
        license_file.symlink_to(self.repo / "LICENSE")
        with self.assertRaisesRegex(release.ReleaseError, "non-regular"):
            release.verify_bundle(bundle)

    def test_failed_build_cleans_stage_and_does_not_publish(self):
        # Exercise the real builder failure path without any available executable.
        with self.assertRaises(RuntimeError):
            self.create(rebuild=True, arduino_cli=str(self.root / "no-such-arduino-cli"))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_rebuilt_hex_mismatch_cleans_stage_and_does_not_publish(self):
        def mismatched_build(source, output, cli):
            for _, _, path in release.VARIANTS:
                (output / Path(path).name).write_bytes(image(b"\x09\x08\x07\x06"))
            return {}
        with patch("build_firmware.build_firmware", side_effect=mismatched_build):
            with self.assertRaisesRegex(release.ReleaseError, "differs from committed HEX"):
                self.create(rebuild=True)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_build_receipt_must_match_artifacts_toolchain_and_resource_limits(self):
        # Synthetic receipt exercises offline validation, not a claimed AVR build.
        bundle = self.create()
        manifest = json.loads((bundle / "release-manifest.json").read_bytes())
        receipt = {
            "schema_version": 1, "status": "verified-build", "source_commit": self.commit,
            "fqbn": release.BUILD_FQBN,
            "toolchain": {
                "arduino_cli": {"version": "fixture"},
                "core": {"id": "ATTinyCore:avr", "version": "1.5.2", "path": "/isolated/core"},
                "avr_gcc": {"version": "7.3.0-atmel3.6.1-arduino7", "compiler_version": "avr-gcc 7.3.0"},
            },
            "variants": [],
        }
        for name, product, source in release.VARIANTS:
            filename = Path(source).name
            properties = ["compiler.c.elf.extra_flags=-Wl,--relax"]
            if name == "mini":
                properties.append("compiler.cpp.extra_flags=-DWITTY_PI_4_MINI")
            command = ["arduino-cli", "compile", "--fqbn", release.BUILD_FQBN,
                       "--clean", "--build-path", "/isolated/build"]
            for value in properties:
                command.extend(["--build-property", value])
            command.append("/isolated/source/" + str(Path(source).parent))
            compiler_hex = (bundle / filename).read_bytes().replace(b"\n", b"\r\n")
            receipt["variants"].append({
                "name": name, "product_id": product, "sketch": str(Path(source).parent),
                "hex_file": filename, **release.describe((bundle / filename).read_bytes()),
                "compiler_hex_sha256": release.sha256(compiler_hex),
                "compiler_hex_size_bytes": len(compiler_hex),
                "compiler_hex_line_endings": "CRLF", "artifact_hex_line_endings": "LF",
                "flash_bytes": 4, "flash_capacity_bytes": 8192,
                "static_ram_bytes": 100, "ram_capacity_bytes": 512,
                "command": command, "build_properties": properties,
            })
        receipt_file = bundle / "build-verification.json"
        receipt_file.write_bytes(release.json_bytes(receipt))
        manifest["artifacts"][receipt_file.name] = {}
        manifest["provenance"]["build"] = "rebuilt-byte-identical"
        self.resign(bundle, manifest)
        release.verify_bundle(bundle)
        original = json.loads(receipt_file.read_bytes())
        mutations = (
            ("hash", lambda r: r["variants"][0].update(sha256="0" * 64)),
            ("compiler-hash", lambda r: r["variants"][0].update(compiler_hex_sha256="0" * 64)),
            ("compiler-encoding", lambda r: r["variants"][0].update(compiler_hex_line_endings="LF")),
            ("flash", lambda r: r["variants"][0].update(flash_bytes=5)),
            ("ram", lambda r: r["variants"][0].update(static_ram_bytes=513)),
            ("source", lambda r: r.update(source_commit="0" * 40)),
            ("core", lambda r: r["toolchain"]["core"].update(version="1.0")),
            ("fqbn", lambda r: r.update(fqbn="ATTinyCore:avr:wrong")),
            ("flags", lambda r: r["variants"][1].update(build_properties=["compiler.c.elf.extra_flags=-Wl,--relax"])),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                changed = json.loads(json.dumps(original))
                mutate(changed)
                receipt_file.write_bytes(release.json_bytes(changed))
                self.resign(bundle)
                with self.assertRaises(release.ReleaseError):
                    release.verify_bundle(bundle)


class HistoricalBundleTests(unittest.TestCase):
    def test_published_historical_bundles_keep_offline_verification(self):
        root = Path(__file__).resolve().parents[2] / "release"
        bundles = (
            ("wp4-4.23-fw7-d466cbc18aae", "legacy-rev7", "archived-not-rebuilt"),
            ("wp4-4.23-fw9-8159567738cd", "atomic-rev9", "rebuilt-byte-identical"),
            ("wp4-4.23-fw9-ca63d2145fa2", "atomic-rev9", "rebuilt-byte-identical"),
            ("wp4-4.24-fw10-234f89a73a42", "scheduled-rev10", "rebuilt-byte-identical"),
            ("wp4-4.25-fw11-286a7d43c1b4", "scheduled-rev11", "rebuilt-byte-identical"),
        )
        # Verification consumes published bytes; it never rebuilds/backports them.
        with patch("release.git", side_effect=AssertionError("Historical verification used Git")):
            with patch("build_firmware.build_firmware",
                       side_effect=AssertionError("Historical verification tried to rebuild")):
                for name, profile, provenance in bundles:
                    with self.subTest(bundle=name):
                        manifest = release.verify_bundle(root / name)
                        self.assertEqual(manifest["profile"], profile)
                        self.assertEqual(manifest["provenance"]["build"], provenance)
                        if profile not in release.REBUILD_REQUIRED:
                            self.assertNotIn("rtc_trust", manifest["compatibility"])


class IntelHexTests(unittest.TestCase):
    def test_valid_sparse_image_and_extended_address(self):
        data = hex_record(0, 4, b"\x00\x00") + hex_record(16, 0, b"\x01\x02") + hex_record(0, 1)
        self.assertEqual(release.intel_hex(data), {"data_bytes": 2, "address_span_bytes": 18, "capacity_bytes": 8192})

    def test_invalid_records_and_addressing_are_rejected(self):
        invalid = {
            "checksum": b":00000001FE\n",
            "missing-eof": hex_record(0, 0, b"\x01"),
            "after-eof": image() + hex_record(4, 0, b"\x01"),
            "overlap": hex_record(0, 0, b"\x01\x02") + hex_record(1, 0, b"\x03") + hex_record(0, 1),
            "capacity": hex_record(8191, 0, b"\x01\x02") + hex_record(0, 1),
            "extended-capacity": hex_record(0, 4, b"\x00\x01") + image(),
            "no-data": hex_record(0, 1),
            "unknown-kind": hex_record(0, 6) + image(),
            "malformed-eof": hex_record(1, 1),
            "malformed-extended": hex_record(0, 4, b"\x00") + image(),
            "non-ascii": b"\xff\n",
        }
        for reason, data in invalid.items():
            with self.subTest(reason=reason):
                with self.assertRaises(release.ReleaseError):
                    release.intel_hex(data)


if __name__ == "__main__":
    unittest.main()
