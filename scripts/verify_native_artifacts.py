#!/usr/bin/env python3
"""Verify every source-built Android ELF against the runtime contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ElfInspection:
    path: str
    bytes: int
    sha256: str
    elf_class: str
    machine: str
    android_api: int
    soname: str
    needed: list[str]
    defined_symbols: list[str]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_tool(arguments: list[str]) -> str:
    result = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout


def read_lines(path: Path) -> list[str]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(lines) != len(set(lines)):
        raise ValueError(f"Duplicate entries in {path}")
    return lines


def readobj_header_and_notes(tool: str, library: Path) -> dict:
    output = run_tool(
        [
            tool,
            "--elf-output-style=JSON",
            "--file-headers",
            "--notes",
            str(library),
        ]
    )
    document = json.loads(output)
    if len(document) != 1 or len(document[0]) != 1:
        raise ValueError(f"Unexpected llvm-readobj JSON for {library}")
    return next(iter(document[0].values()))


def parse_android_api(document: dict) -> int:
    for entry in document.get("Notes", []):
        section = entry.get("NoteSection", {})
        if section.get("Name") != ".note.android.ident":
            continue
        data = section.get("Note", {}).get("Description data", {}).get("Bytes")
        if not isinstance(data, list) or len(data) < 4:
            break
        return int.from_bytes(bytes(data[:4]), "little")
    raise ValueError("ELF is missing a valid .note.android.ident API level.")


def parse_needed(output: str) -> list[str]:
    match = re.search(r"NeededLibraries\s*\[(.*?)\]", output, re.DOTALL)
    if match is None:
        raise ValueError("llvm-readobj output has no NeededLibraries block.")
    return sorted(line.strip() for line in match.group(1).splitlines() if line.strip())


def parse_defined_symbols(output: str) -> list[str]:
    symbols = []
    for line in output.splitlines():
        fields = line.split()
        if not fields:
            continue
        symbol = fields[0].split("@", 1)[0]
        symbols.append(symbol)
    return sorted(set(symbols))


def inspect_elf(
    path: Path,
    relative: str,
    llvm_readobj: str,
    llvm_nm: str,
) -> ElfInspection:
    if path.is_symlink():
        raise ValueError(f"Native library must not be a symlink: {relative}")
    if path.read_bytes()[:4] != b"\x7fELF":
        raise ValueError(f"Native library is not ELF: {relative}")
    document = readobj_header_and_notes(llvm_readobj, path)
    header = document["ElfHeader"]
    summary = document["FileSummary"]
    if header["Ident"]["DataEncoding"]["Value"] != "LittleEndian":
        raise ValueError(f"Native library is not little-endian: {relative}")
    if not header["Type"].startswith("SharedObject"):
        raise ValueError(f"Native library is not a shared object: {relative}")
    needed = parse_needed(
        run_tool([llvm_readobj, "--needed-libs", str(path)])
    )
    symbols = parse_defined_symbols(
        run_tool(
            [
                llvm_nm,
                "-D",
                "--defined-only",
                "--format=posix",
                str(path),
            ]
        )
    )
    return ElfInspection(
        path=relative,
        bytes=path.stat().st_size,
        sha256=sha256(path),
        elf_class=header["Ident"]["Class"]["Value"],
        machine=header["Machine"]["Value"],
        android_api=parse_android_api(document),
        soname=summary["LoadName"],
        needed=needed,
        defined_symbols=symbols,
    )


def expected_native_paths(contract: dict, mode: str) -> dict[str, tuple[str, str]]:
    paths = {}
    for library, abis in contract["nativeLibraries"].items():
        if mode == "available-components" and library == "libLiteRtClGlAccelerator.so":
            continue
        for abi in abis:
            paths[f"{abi}/{library}"] = (abi, library)
    return paths


def validate_inspection(
    inspection: ElfInspection,
    abi: str,
    library: str,
    contract: dict,
    contract_root: Path,
) -> list[str]:
    errors = []
    native = contract["nativeValidation"]
    abi_policy = native["abis"][abi]
    library_policy = native["libraries"][library]
    if inspection.elf_class != abi_policy["class"]:
        errors.append(
            f"{inspection.path}: class {inspection.elf_class}, "
            f"expected {abi_policy['class']}"
        )
    if inspection.machine != abi_policy["machine"]:
        errors.append(
            f"{inspection.path}: machine {inspection.machine}, "
            f"expected {abi_policy['machine']}"
        )
    if inspection.android_api != native["androidApi"]:
        errors.append(
            f"{inspection.path}: Android API {inspection.android_api}, "
            f"expected {native['androidApi']}"
        )
    if inspection.soname not in library_policy["sonames"]:
        errors.append(
            f"{inspection.path}: SONAME {inspection.soname!r} is not allowed"
        )
    expected_needed = sorted(library_policy["needed"])
    if inspection.needed != expected_needed:
        errors.append(
            f"{inspection.path}: DT_NEEDED {inspection.needed}, "
            f"expected {expected_needed}"
        )

    required = set(library_policy.get("requiredSymbols", []))
    required_file = library_policy.get("requiredSymbolsFile")
    if required_file:
        required.update(read_lines(contract_root / required_file))
    missing = sorted(required - set(inspection.defined_symbols))
    if missing:
        errors.append(f"{inspection.path}: missing symbols {missing}")

    exported_file = library_policy.get("exportedJniSymbolsFile")
    if exported_file:
        expected_jni = set(read_lines(contract_root / exported_file))
        actual_jni = {
            symbol
            for symbol in inspection.defined_symbols
            if symbol.startswith("Java_")
        }
        if actual_jni != expected_jni:
            errors.append(
                f"{inspection.path}: JNI export drift; "
                f"missing={sorted(expected_jni - actual_jni)}, "
                f"extra={sorted(actual_jni - expected_jni)}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-dir", type=Path, required=True)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("contracts/complete-runtime-contract.json"),
    )
    parser.add_argument(
        "--mode",
        choices=("available-components", "complete"),
        required=True,
    )
    parser.add_argument("--llvm-readobj", default="llvm-readobj")
    parser.add_argument("--llvm-nm", default="llvm-nm")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    native_dir = args.native_dir.resolve()
    contract_path = args.contract.resolve()
    contract_root = contract_path.parents[1]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    expected = expected_native_paths(contract, args.mode)
    actual = {
        path.relative_to(native_dir).as_posix(): path
        for path in native_dir.rglob("*.so")
        if path.is_file()
    }
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    errors = []
    if missing:
        errors.append(f"Missing native libraries: {missing}")
    if extra:
        errors.append(f"Unexpected native libraries: {extra}")

    inspections = []
    for relative in sorted(expected.keys() & actual.keys()):
        abi, library = expected[relative]
        inspection = inspect_elf(
            actual[relative], relative, args.llvm_readobj, args.llvm_nm
        )
        inspections.append(inspection)
        errors.extend(
            validate_inspection(
                inspection, abi, library, contract, contract_root
            )
        )

    report = {
        "schemaVersion": 1,
        "mode": args.mode,
        "contract": contract_path.name,
        "libraries": [asdict(inspection) for inspection in inspections],
        "errors": errors,
    }
    if args.report:
        output = args.report.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Verified {len(inspections)} native libraries in {native_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
