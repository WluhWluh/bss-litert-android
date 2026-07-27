#!/usr/bin/env python3
"""Verify a LiteRT AAR against the Booming SS API and ABI contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aar", type=Path, required=True)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("contracts/complete-runtime-contract.json"),
    )
    parser.add_argument("--mode", choices=("reference", "complete"), required=True)
    parser.add_argument("--javap", default="javap")
    return parser.parse_args()


def class_entry(class_name: str) -> str:
    return class_name.replace(".", "/") + ".class"


def read_contract(path: Path) -> dict:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if contract.get("schemaVersion") != 1:
        raise ValueError("Unsupported complete runtime contract schema.")
    return contract


def inspect_api(
    classes_jar: Path,
    required_members: dict[str, list[str]],
    javap: str,
) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(classes_jar) as archive:
        entries = set(archive.namelist())
    for class_name, members in sorted(required_members.items()):
        if class_entry(class_name) not in entries:
            errors.append(f"Required class is missing: {class_name}")
            continue
        result = subprocess.run(
            [javap, "-classpath", str(classes_jar), "-public", class_name],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(f"javap failed for {class_name}: {result.stderr.strip()}")
            continue
        normalized = " ".join(result.stdout.split())
        for member in members:
            if member not in normalized:
                errors.append(f"Required API member is missing: {class_name}: {member}")
    return errors


def inspect_complete_archive(
    aar_entries: set[str],
    classes_jar: Path,
    contract: dict,
) -> list[str]:
    errors: list[str] = []
    expected_native = {
        f"jni/{abi}/{library}"
        for library, abis in contract["nativeLibraries"].items()
        for abi in abis
    }
    actual_native = {
        entry
        for entry in aar_entries
        if entry.startswith("jni/") and entry.endswith(".so")
    }
    for entry in sorted(expected_native - actual_native):
        errors.append(f"Required native library is missing: {entry}")
    for entry in sorted(actual_native - expected_native):
        errors.append(f"Unexpected native library is packaged: {entry}")

    with zipfile.ZipFile(classes_jar) as archive:
        class_entries = {
            entry for entry in archive.namelist() if entry.endswith(".class")
        }
    for prefix in contract["api"]["forbiddenClassPrefixes"]:
        matches = sorted(entry for entry in class_entries if entry.startswith(prefix))
        if matches:
            errors.append(f"Forbidden API is packaged: {matches[0]}")
    return errors


def main() -> int:
    args = parse_args()
    aar = args.aar.resolve()
    contract = read_contract(args.contract.resolve())
    if not aar.is_file():
        raise FileNotFoundError(f"AAR not found: {aar}")

    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="bss-litert-contract-") as temp:
        classes_jar = Path(temp) / "classes.jar"
        with zipfile.ZipFile(aar) as archive:
            aar_entries = set(archive.namelist())
            if "classes.jar" not in aar_entries:
                errors.append("AAR does not contain classes.jar.")
            else:
                classes_jar.write_bytes(archive.read("classes.jar"))

        if classes_jar.is_file():
            required_members = dict(contract["api"]["requiredMembers"])
            if args.mode == "complete":
                for class_name, members in contract["api"]["bssExtensionMembers"].items():
                    required_members.setdefault(class_name, []).extend(members)
            errors.extend(inspect_api(classes_jar, required_members, args.javap))
            if args.mode == "complete":
                errors.extend(inspect_complete_archive(aar_entries, classes_jar, contract))

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Verified {args.mode} contract: {aar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
