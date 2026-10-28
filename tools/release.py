#!/usr/bin/env python3
"""Export explicit committed WP4 inputs; verify bundles without Git or a toolchain."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import zlib


class ReleaseError(RuntimeError):
    """An input or artifact cannot safely be released."""


PROFILES = {
    "legacy-rev7": {
        "nominal_revision": 7,
        "rtc_reads": "byte",
        "rtc_writes": "byte",
        "revision_source": "EEPROM-overridable",
        "rtc_time_convention": "local time (unchanged)",
    },
    "atomic-rev9": {
        "nominal_revision": 9,
        "rtc_reads": "coherent 7-byte (minimum revision 8)",
        "rtc_writes": "atomic 7-byte calendar (minimum revision 9)",
        "revision_source": "running image",
        "rtc_time_convention": "local time (unchanged)",
    },
}
BUILD_FQBN = (
    "ATTinyCore:avr:attinyx41:chip=841,clock=8internal,pinmapping=old,"
    "LTO=enable,wiremode=slave,neopixelport=porta,millis=disabled,"
    "eesave=aenable,bod=2v7,bodact=enabled,bodpd=enabled"
)
VARIANTS = (
    ("standard", "0x26", "Firmware/WittyPi4/WittyPi4.ino.hex"),
    ("mini", "0x36", "Firmware/WittyPi4/WittyPi4_Mini.ino.hex"),
    ("l3v7", "0x37", "Firmware/WittyPi4_L3V7/WittyPi4_L3V7.ino.hex"),
)
SKETCHES = ("Firmware/WittyPi4/WittyPi4.ino", "Firmware/WittyPi4_L3V7/WittyPi4_L3V7.ino")
BASE_ARTIFACTS = {"source.tar.gz", "wittypi-software.tar.gz", "LICENSE"} | {
    PurePosixPath(path).name for _, _, path in VARIANTS
}
QUALIFICATION = {
    "hardware": "not established",
    "deployment": "not established",
    "runtime_identity": "Product/revision does not prove an exact Git build.",
}
PROVENANCE = {
    "source": "committed Git blobs; no working-tree inputs",
    "binary": "unchanged committed Intel HEX blobs",
    "profile": "explicit maintainer-reviewed metadata; not automatic ABI discovery",
    "authenticity": "Checksums detect corruption, not authenticity; consumers must pin the manifest SHA256.",
}


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def safe_path(name):
    require(isinstance(name, str) and bool(name), "Empty or non-string artifact path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and str(path) == name and
            all(part not in (".", "..") for part in path.parts) and
            "\\" not in name and not any(ord(c) < 32 for c in name),
            f"Unsafe artifact path: {name!r}")
    return path


def source_path(name):
    path = safe_path(name)
    require(name in ("README.md", "LICENSE") or
            (len(path.parts) > 1 and path.parts[0] in ("Firmware", "Software")),
            f"Unexpected source path: {name}")


def intel_hex(data):
    """Validate checksums, addressing, EOF and ATtiny841 flash bounds."""
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ReleaseError("Intel HEX is not ASCII") from exc
    occupied = set()
    base = 0
    eof = False
    for number, line in enumerate(lines, 1):
        require(not eof, f"Intel HEX data after EOF at line {number}")
        require(re.fullmatch(r":[0-9A-Fa-f]+", line) is not None and len(line) % 2 == 1,
                f"Invalid Intel HEX record at line {number}")
        record = bytes.fromhex(line[1:])
        require(len(record) >= 5 and len(record) == record[0] + 5 and sum(record) % 256 == 0,
                f"Invalid Intel HEX length/checksum at line {number}")
        size, address, kind = record[0], int.from_bytes(record[1:3], "big"), record[3]
        payload = record[4:-1]
        if kind == 0:
            start = base + address
            require(size > 0 and start + size <= 8192 and address + size <= 65536,
                    f"Intel HEX exceeds flash bounds at line {number}")
            addresses = set(range(start, start + size))
            require(not occupied.intersection(addresses), f"Overlapping Intel HEX at line {number}")
            occupied.update(addresses)
        elif kind == 1:
            require(size == 0 and address == 0, "Malformed Intel HEX EOF")
            eof = True
        elif kind in (2, 4):
            require(size == 2 and address == 0, "Malformed Intel HEX extended address")
            base = int.from_bytes(payload, "big") << (4 if kind == 2 else 16)
        elif kind in (3, 5):
            require(size == 4 and address == 0, "Malformed Intel HEX start address")
            start = (int.from_bytes(payload[:2], "big") * 16 + int.from_bytes(payload[2:], "big")
                     if kind == 3 else int.from_bytes(payload, "big"))
            require(start < 8192, "Intel HEX start address exceeds flash bounds")
        else:
            raise ReleaseError(f"Unsupported Intel HEX record type {kind}")
    require(eof and bool(occupied), "Intel HEX needs data and a final EOF")
    return {"data_bytes": len(occupied), "address_span_bytes": max(occupied) + 1,
            "capacity_bytes": 8192}


def metadata(files, profile):
    require(profile in PROFILES, f"Unsupported profile: {profile}")
    try:
        versions = re.findall(rb"^\s*SOFTWARE_VERSION=['\"]([0-9]+(?:\.[0-9]+)+)['\"]\s*$",
                              files["Software/wittypi/utilities.sh"][1], re.M)
        require(len(versions) == 1, "Missing or ambiguous software version in utilities.sh")
        for path in SKETCHES:
            revisions = re.findall(rb"^\s*i2cReg\[I2C_FW_REVISION\]\s*=\s*(0x[0-9a-fA-F]+|[0-9]+)\s*;\s*(?://[^\n]*)?$",
                                   files[path][1], re.M)
            require(len(revisions) == 1 and int(revisions[0], 0) == PROFILES[profile]["nominal_revision"],
                    f"Declared firmware revision in {path} does not match {profile}")
    except KeyError as exc:
        raise ReleaseError(f"Missing required source: {exc.args[0]}") from exc
    return versions[0].decode("ascii")


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    require(result.returncode == 0, "Git input failed: " + result.stderr.decode(errors="replace").strip())
    return result.stdout


def committed_snapshot(repo, ref):
    require(bool(ref) and not ref.startswith("-"), "An explicit Git ref is required")
    commit = git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
    tree = git(repo, "rev-parse", commit + "^{tree}").decode().strip()
    timestamp = int(git(repo, "show", "-s", "--format=%ct", commit))
    files = {}
    objects = {}
    listing = git(repo, "ls-tree", "-rz", commit, "--", "Firmware", "Software", "README.md", "LICENSE")
    for item in listing.split(b"\0"):
        if not item:
            continue
        header, raw_name = item.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        name = raw_name.decode("utf-8")
        source_path(name)
        require(kind == "blob" and mode in ("100644", "100755"),
                f"Only regular committed files are supported: {name}")
        files[name] = (int(mode, 8) & 0o777, git(repo, "cat-file", "blob", oid))
        objects[name] = {"git_mode": mode, "git_blob": oid}
    require("README.md" in files and "LICENSE" in files, "Source needs README.md and LICENSE")
    return {"commit": commit, "tree": tree, "commit_timestamp": timestamp, "files": objects}, files


def write_archive(path, files, timestamp):
    # No filename or wall-clock timestamp in gzip; no host uid/gid in tar.
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for name, (mode, data) in sorted(files.items()):
                    safe_path(name)
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    member.mode = mode
                    member.mtime = timestamp
                    archive.addfile(member, io.BytesIO(data))


def read_archive(path):
    files = {}
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                safe_path(member.name)
                require(member.isfile() and not member.issparse(), f"Non-regular archive member: {member.name}")
                require(member.name not in files, f"Duplicate archive member: {member.name}")
                require(member.mode in (0o644, 0o755), f"Unsupported archive mode: {member.name}")
                files[member.name] = (member.mode, archive.extractfile(member).read())
    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:
        raise ReleaseError(f"Invalid archive {path.name}: {exc}") from exc
    return files


def software_files(files):
    return {name[len("Software/"):]: value for name, value in files.items()
            if name.startswith("Software/wittypi/")}


def describe(data):
    return {"sha256": sha256(data), "size_bytes": len(data)}


def variant_metadata(files):
    variants = []
    for name, product, source in VARIANTS:
        require(source in files, f"Missing firmware artifact: {source}")
        variants.append({"name": name, "product_id": product, "source_path": source,
                         "artifact": PurePosixPath(source).name,
                         "flash": intel_hex(files[source][1])})
    return variants


def load_json(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, f"Duplicate JSON key: {key}")
            value[key] = item
        return value
    try:
        return json.loads(path.read_bytes(), object_pairs_hook=unique)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ReleaseError(f"Invalid JSON in {path.name}: {exc}") from exc


def verify_receipt(receipt, manifest, bundle):
    require(isinstance(receipt, dict) and receipt.get("schema_version") == 1 and
            receipt.get("status") == "verified-build" and
            receipt.get("source_commit") == manifest["source"]["commit"], "Invalid build receipt identity")
    toolchain = receipt.get("toolchain")
    require(isinstance(toolchain, dict), "Missing build toolchain")
    core = toolchain.get("core", {})
    require(isinstance(core, dict) and core.get("id") == "ATTinyCore:avr" and
            core.get("version") == "1.5.2", "Wrong build core")
    gcc = toolchain.get("avr_gcc", {})
    cli = toolchain.get("arduino_cli", {})
    require(isinstance(gcc, dict) and gcc.get("version") == "7.3.0-atmel3.6.1-arduino7" and
            isinstance(gcc.get("compiler_version"), str) and bool(gcc["compiler_version"]), "Wrong build compiler")
    require(isinstance(cli, dict) and isinstance(cli.get("version"), str) and bool(cli["version"]),
            "Missing Arduino CLI version")
    require(receipt.get("fqbn") == BUILD_FQBN, "Wrong build FQBN")
    observed = receipt.get("variants")
    require(isinstance(observed, list) and len(observed) == len(VARIANTS), "Invalid build variants")
    for item, expected in zip(observed, manifest["variants"]):
        require(isinstance(item, dict), "Invalid build variant")
        artifact = expected["artifact"]
        require(item.get("name") == expected["name"] and item.get("product_id") == expected["product_id"] and
                item.get("hex_file") == artifact and
                item.get("sketch") == str(PurePosixPath(expected["source_path"]).parent),
                "Build variant identity mismatch")
        artifact_bytes = (bundle / artifact).read_bytes()
        for key, value in describe(artifact_bytes).items():
            require(item.get(key) == value, f"Build receipt {key} mismatch: {artifact}")
        line_endings = item.get("compiler_hex_line_endings")
        require(item.get("artifact_hex_line_endings") == "LF" and b"\r" not in artifact_bytes and
                line_endings in ("LF", "CRLF"), "Invalid build HEX line endings")
        compiler_bytes = artifact_bytes.replace(b"\n", b"\r\n") if line_endings == "CRLF" else artifact_bytes
        require(item.get("compiler_hex_sha256") == sha256(compiler_bytes) and
                item.get("compiler_hex_size_bytes") == len(compiler_bytes),
                f"Compiler HEX normalization mismatch: {artifact}")
        require(type(item.get("flash_bytes")) is int and
                item["flash_bytes"] == expected["flash"]["data_bytes"] and item.get("flash_capacity_bytes") == 8192,
                f"Build flash usage mismatch: {artifact}")
        require(type(item.get("static_ram_bytes")) is int and 0 <= item["static_ram_bytes"] <= 512 and
                item.get("ram_capacity_bytes") == 512, f"Invalid build RAM usage: {artifact}")
        for key in ("command", "build_properties"):
            require(isinstance(item.get(key), list) and bool(item[key]) and
                    all(isinstance(value, str) for value in item[key]), f"Missing build {key}")
        properties = ["compiler.c.elf.extra_flags=-Wl,--relax"]
        if expected["name"] == "mini":
            properties.append("compiler.cpp.extra_flags=-DWITTY_PI_4_MINI")
        require(item["build_properties"] == properties, "Wrong build properties")
        command = item["command"]
        require(len(command) >= 5 and command[1:4] == ["compile", "--fqbn", BUILD_FQBN] and
                "--clean" in command and "--build-path" in command, "Inconsistent build command")
        command_properties = [command[index + 1] for index, value in enumerate(command[:-1])
                              if value == "--build-property"]
        require(command_properties == properties, "Build command properties mismatch")


def verify_bundle(bundle):
    bundle = Path(bundle)
    require(bundle.is_dir() and not bundle.is_symlink(), "Bundle must be a regular directory")
    entries = list(bundle.iterdir())
    require(all(path.is_file() and not path.is_symlink() for path in entries), "Bundle contains non-regular files")
    require((bundle / "release-manifest.json").is_file(), "Missing release manifest")
    manifest = load_json(bundle / "release-manifest.json")
    require(isinstance(manifest, dict) and type(manifest.get("schema_version")) is int and
            manifest["schema_version"] == 1 and manifest.get("project") == "Witty-Pi-4", "Unsupported release manifest")
    profile = manifest.get("profile")
    require(isinstance(profile, str) and profile in PROFILES and manifest.get("compatibility") == PROFILES[profile],
            "Invalid release profile metadata")
    provenance = manifest.get("provenance")
    require(isinstance(provenance, dict) and provenance.get("build") in ("archived-not-rebuilt", "rebuilt-byte-identical") and
            all(provenance.get(key) == value for key, value in PROVENANCE.items()), "Invalid provenance metadata")
    require(manifest.get("qualification") == QUALIFICATION, "Unsupported qualification claims")
    rebuilt = provenance["build"] == "rebuilt-byte-identical"
    require(not rebuilt or profile == "atomic-rev9", "Legacy images are archived, not rebuilt")
    expected = BASE_ARTIFACTS | ({"build-verification.json"} if rebuilt else set())
    artifacts = manifest.get("artifacts")
    require(isinstance(artifacts, dict), "Missing artifacts")
    for name in artifacts:
        safe_path(name)
    require(set(artifacts) == expected, "Unexpected manifest artifact set")
    require({path.name for path in entries} == expected | {"release-manifest.json", "SHA256SUMS"},
            "Unexpected or missing bundle files")
    for name, info in artifacts.items():
        require(info == describe((bundle / name).read_bytes()), f"Artifact hash/size mismatch: {name}")
    expected_sums = "".join(f"{sha256((bundle / name).read_bytes())}  {name}\n"
                            for name in sorted(expected | {"release-manifest.json"}))
    require((bundle / "SHA256SUMS").read_bytes() == expected_sums.encode(), "SHA256SUMS mismatch")
    source = manifest.get("source")
    require(isinstance(source, dict) and all(isinstance(source.get(key), str) and
            re.fullmatch(r"[0-9a-f]{40}", source[key]) for key in ("commit", "tree")) and
            type(source.get("commit_timestamp")) is int and source["commit_timestamp"] >= 0,
            "Invalid source Git metadata")
    files = read_archive(bundle / "source.tar.gz")
    objects = source.get("files")
    require(isinstance(objects, dict) and set(objects) == set(files), "Source inventory mismatch")
    require("README.md" in files and "LICENSE" in files, "Missing source README or LICENSE")
    for name, (mode, data) in files.items():
        source_path(name)
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(objects[name] == {"git_mode": f"100{mode:o}", "git_blob": blob}, f"Source Git blob/mode mismatch: {name}")
    version = metadata(files, profile)
    require(manifest.get("software_version") == version, "Software version mismatch")
    name = f"wp4-{version}-fw{PROFILES[profile]['nominal_revision']}-{source['commit'][:12]}"
    require(manifest.get("release_name") == name, "Release name mismatch")
    require(manifest.get("variants") == variant_metadata(files), "Firmware metadata mismatch")
    require(read_archive(bundle / "wittypi-software.tar.gz") == software_files(files), "Software archive/source mismatch")
    for _, _, path in VARIANTS:
        require((bundle / PurePosixPath(path).name).read_bytes() == files[path][1], f"Firmware/source mismatch: {path}")
    require((bundle / "LICENSE").read_bytes() == files["LICENSE"][1], "LICENSE/source mismatch")
    if rebuilt:
        verify_receipt(load_json(bundle / "build-verification.json"), manifest, bundle)
    return manifest


def create_release(repo, ref, profile, output=None, rebuild=False, arduino_cli="arduino-cli"):
    repo = Path(repo)
    source, files = committed_snapshot(repo, ref)
    version = metadata(files, profile)
    variants = variant_metadata(files)
    require(not rebuild or profile == "atomic-rev9", "Historical legacy-rev7 images must be archived without rebuilding")
    name = f"wp4-{version}-fw{PROFILES[profile]['nominal_revision']}-{source['commit'][:12]}"
    root = Path(output) if output is not None else repo / "release"
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    require(not os.path.lexists(target), f"Release already exists: {target}")
    # Serialize publishers of this release name; the final directory appears only
    # after validation. Fail closed on a stale lock rather than guess ownership.
    lock = root / ("." + name + ".lock")
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ReleaseError(f"Release publication already reserved: {target}") from exc
    try:
        require(not os.path.lexists(target), f"Release already exists: {target}")
        with tempfile.TemporaryDirectory(prefix=".wp4-stage-", dir=root) as temporary:
            workspace = Path(temporary)
            stage = workspace / "bundle"
            stage.mkdir()
            write_archive(stage / "source.tar.gz", files, source["commit_timestamp"])
            write_archive(stage / "wittypi-software.tar.gz", software_files(files), source["commit_timestamp"])
            (stage / "LICENSE").write_bytes(files["LICENSE"][1])
            for _, _, path in VARIANTS:
                (stage / PurePosixPath(path).name).write_bytes(files[path][1])
            manifest = {"schema_version": 1, "project": "Witty-Pi-4", "release_name": name,
                        "source": source, "software_version": version, "profile": profile,
                        "compatibility": PROFILES[profile], "variants": variants,
                        "qualification": QUALIFICATION,
                        "provenance": dict(PROVENANCE, build="archived-not-rebuilt")}
            if rebuild:
                from build_firmware import build_firmware
                snapshot = workspace / "source"
                snapshot.mkdir()
                for path, (mode, data) in files.items():
                    destination = snapshot / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                    destination.chmod(mode)
                build = workspace / "build"
                build.mkdir()
                receipt = build_firmware(snapshot, build, arduino_cli)
                for _, _, path in VARIANTS:
                    filename = PurePosixPath(path).name
                    compiled = build / filename
                    require(compiled.is_file() and not compiled.is_symlink(), f"Build did not produce {filename}")
                    actual, expected = compiled.read_bytes(), files[path][1]
                    require(actual == expected, f"Rebuilt {filename} differs from committed HEX: "
                            f"built sha256={sha256(actual)}, committed sha256={sha256(expected)}")
                require(isinstance(receipt, dict), "Builder returned an invalid receipt")
                receipt["source_commit"] = source["commit"]
                (stage / "build-verification.json").write_bytes(json_bytes(receipt))
                manifest["provenance"]["build"] = "rebuilt-byte-identical"
            manifest["artifacts"] = {path.name: describe(path.read_bytes()) for path in sorted(stage.iterdir())}
            (stage / "release-manifest.json").write_bytes(json_bytes(manifest))
            (stage / "SHA256SUMS").write_text("".join(
                f"{sha256(path.read_bytes())}  {path.name}\n" for path in sorted(stage.iterdir())), encoding="ascii")
            verify_bundle(stage)
            require(not os.path.lexists(target), f"Release already exists: {target}")
            stage.rename(target)
    finally:
        lock.rmdir()
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Export an explicit immutable Git commit")
    create.add_argument("--ref", required=True)
    create.add_argument("--profile", required=True, choices=PROFILES)
    create.add_argument("--output", type=Path)
    create.add_argument("--rebuild", action="store_true")
    create.add_argument("--arduino-cli", default="arduino-cli")
    verify = commands.add_parser("verify", help="Verify a standalone bundle offline")
    verify.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            path = create_release(Path(__file__).resolve().parent.parent, args.ref, args.profile,
                                  args.output, args.rebuild, args.arduino_cli)
            print(path)
        else:
            manifest = verify_bundle(args.bundle)
            print(f"Verified {manifest['release_name']} (integrity only; not hardware qualification or authenticity)")
    except (RuntimeError, OSError, ValueError, tarfile.TarError) as exc:
        print(f"release: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
