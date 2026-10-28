"""Offline, pinned-toolchain builds for immutable Witty Pi 4 source snapshots."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


CORE_VERSION = "1.5.2"
GCC_VERSION = "7.3.0-atmel3.6.1-arduino7"
FQBN = (
    "ATTinyCore:avr:attinyx41:chip=841,clock=8internal,pinmapping=old,"
    "LTO=enable,wiremode=slave,neopixelport=porta,millis=disabled,"
    "eesave=aenable,bod=2v7,bodact=enabled,bodpd=enabled"
)
VARIANTS = (
    ("standard", "0x26", "WittyPi4", "WittyPi4.ino.hex"),
    ("mini", "0x36", "WittyPi4", "WittyPi4_Mini.ino.hex"),
    ("l3v7", "0x37", "WittyPi4_L3V7", "WittyPi4_L3V7.ino.hex"),
)


def _run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command, text=True, capture_output=True, check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except OSError as exc:
        raise RuntimeError(f"Cannot execute {command[0]}: {exc}") from exc
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {command!r}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def _properties(text: str) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in text.splitlines()
        if "=" in line and not line.startswith("#")
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hex_bytes(data: bytes) -> tuple[bytes, str]:
    """Match Git's LF text storage without changing any Intel HEX record."""
    if b"\r" not in data:
        return data, "LF"
    if data.count(b"\r\n") != data.count(b"\n") or b"\r" in data.replace(b"\r\n", b""):
        raise RuntimeError("Compiler HEX has mixed or invalid line endings")
    return data.replace(b"\r\n", b"\n"), "CRLF"


def _toolchain(properties: dict[str, str]) -> tuple[dict, Path]:
    required = (
        "runtime.platform.path", "runtime.tools.avr-gcc.path", "compiler.path",
        f"runtime.tools.avr-gcc-{GCC_VERSION}.path",
    )
    if any(not properties.get(key) for key in required):
        raise RuntimeError("Arduino did not resolve the required pinned AVR toolchain")
    platform = Path(properties["runtime.platform.path"]).resolve()
    platform_file = platform / "platform.txt"
    try:
        platform_properties = _properties(platform_file.read_text())
    except OSError as exc:
        raise RuntimeError(f"Cannot read selected core metadata: {exc}") from exc
    if platform_properties.get("version") != CORE_VERSION:
        raise RuntimeError(f"Required ATTinyCore {CORE_VERSION}; selected {platform}")
    gcc_root = Path(properties["runtime.tools.avr-gcc.path"]).resolve()
    pinned_root = Path(properties[f"runtime.tools.avr-gcc-{GCC_VERSION}.path"]).resolve()
    compiler_bin = Path(properties["compiler.path"]).resolve()
    if gcc_root != pinned_root or gcc_root.name != GCC_VERSION or compiler_bin != gcc_root / "bin":
        raise RuntimeError(f"Required AVR GCC package {GCC_VERSION}; selected {compiler_bin}")
    gcc = compiler_bin / "avr-gcc"
    compiler_version = _run([str(gcc), "--version"]).stdout.splitlines()[0]
    if not re.search(r"\b7\.3\.0\b", compiler_version):
        raise RuntimeError(f"Required AVR GCC 7.3.0; observed {compiler_version}")
    return {
        "core": {
            "id": "ATTinyCore:avr", "version": CORE_VERSION,
            "path": str(platform), "platform_sha256": _sha256(platform_file),
        },
        "avr_gcc": {
            "version": GCC_VERSION, "compiler_version": compiler_version,
            "path": str(gcc), "compiler_sha256": _sha256(gcc),
        },
    }, compiler_bin


def _resource_usage(size_output: str) -> tuple[int, int, dict[str, int]]:
    sections = {}
    for line in size_output.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0].startswith("."):
            try:
                size = int(fields[1])
            except ValueError as exc:
                raise RuntimeError(f"Invalid avr-size output: {line}") from exc
            if size < 0 or fields[0] in sections:
                raise RuntimeError(f"Invalid or duplicate ELF section: {line}")
            sections[fields[0]] = size
    if sections.get(".text", 0) <= 0:
        raise RuntimeError("avr-size did not report a nonempty .text section")
    flash = sum(sections.get(name, 0) for name in (".text", ".data", ".bootloader"))
    ram = sum(sections.get(name, 0) for name in (".data", ".bss", ".noinit"))
    if flash > 8192 or ram > 512:
        raise RuntimeError(f"ATtiny841 capacity exceeded: flash {flash}/8192, static RAM {ram}/512")
    return flash, ram, sections


def build_firmware(source: Path, output: Path, arduino_cli: str) -> dict:
    """Build all three variants; fail rather than substituting unverified artifacts.

    The caller supplies an installed CLI/toolchain and an empty output directory.
    No packages are installed, configuration changed, or hardware accessed here.
    Work files are confined to output and removed on both success and failure.
    The caller must compare returned HEX files with the committed release inputs.
    """
    source = Path(source).resolve()
    output = Path(output).resolve()
    if not source.is_dir():
        raise RuntimeError(f"Missing source snapshot: {source}")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise RuntimeError(f"Build output must be a new or empty directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    version_command = [arduino_cli, "version", "--format", "json"]
    try:
        cli_version = json.loads(_run(version_command).stdout)["VersionString"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Cannot read Arduino CLI version JSON") from exc
    if not isinstance(cli_version, str) or not cli_version:
        raise RuntimeError("Arduino CLI did not identify its version")
    receipt = {
        "schema_version": 1, "status": "verified-build", "fqbn": FQBN,
        "toolchain": {"arduino_cli": {"version": cli_version, "command": version_command}},
        "variants": [],
    }
    artifacts = {}
    # No export-binaries/output-dir: ATTinyCore's export hook writes .lst into
    # the sketch. Read fresh HEX directly from the isolated build path instead.
    with tempfile.TemporaryDirectory(prefix=".build-", dir=output) as temporary:
        work = Path(temporary)
        for name, product_id, sketch_name, hex_name in VARIANTS:
            sketch_relative = f"Firmware/{sketch_name}"
            sketch = source / sketch_relative
            if not (sketch / f"{sketch_name}.ino").is_file():
                raise RuntimeError(f"Missing firmware sketch: {sketch}")
            build_path = work / name
            flags = ["compiler.c.elf.extra_flags=-Wl,--relax"]
            if name == "mini":
                flags.append("compiler.cpp.extra_flags=-DWITTY_PI_4_MINI")
            command = [
                arduino_cli, "compile", "--fqbn", FQBN, "--clean",
                "--build-path", str(build_path),
            ]
            for flag in flags:
                command.extend(["--build-property", flag])
            command.append(str(sketch))
            properties_command = [*command, "--show-properties=expanded"]
            properties = _properties(_run(properties_command).stdout)
            observed, compiler_bin = _toolchain(properties)
            if receipt["variants"] and any(receipt["toolchain"][key] != value for key, value in observed.items()):
                raise RuntimeError("Selected toolchain changed between variants")
            receipt["toolchain"].update(observed)
            build_result = _run(command)
            built_hex = build_path / f"{sketch_name}.ino.hex"
            elf = build_path / f"{sketch_name}.ino.elf"
            if not built_hex.is_file() or not elf.is_file():
                raise RuntimeError(f"Build did not produce HEX and ELF for {name}")
            size_command = [str(compiler_bin / "avr-size"), "-A", str(elf)]
            size_result = _run(size_command)
            flash, ram, sections = _resource_usage(size_result.stdout)
            compiler_hex = built_hex.read_bytes()
            artifact, line_endings = _hex_bytes(compiler_hex)
            artifacts[hex_name] = artifact
            receipt["variants"].append({
                "name": name, "product_id": product_id, "sketch": sketch_relative,
                "hex_file": hex_name, "sha256": hashlib.sha256(artifact).hexdigest(),
                "size_bytes": len(artifact),
                "compiler_hex_sha256": hashlib.sha256(compiler_hex).hexdigest(),
                "compiler_hex_size_bytes": len(compiler_hex),
                "compiler_hex_line_endings": line_endings,
                "artifact_hex_line_endings": "LF",
                "flash_bytes": flash, "flash_capacity_bytes": 8192,
                "static_ram_bytes": ram, "ram_capacity_bytes": 512,
                "build_properties": flags, "command": command,
                "properties_command": properties_command, "size_command": size_command,
                "sections": sections, "elf_sha256": _sha256(elf),
                "build_stdout": build_result.stdout, "build_stderr": build_result.stderr,
                "size_stdout": size_result.stdout,
            })
        # Publish outputs only after all three complete and pass capacity checks.
        for hex_name, artifact in artifacts.items():
            (output / hex_name).write_bytes(artifact)
    return receipt
