#!/usr/bin/env python3
"""Assemble the complete deterministic Booming SS LiteRT Android AAR."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from deterministic_archive import write_archive


REPLACED_API_ENTRIES = {
    "consumer-rules.pro",
    "proguard.txt",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-aar", type=Path, required=True)
    parser.add_argument("--native-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--consumer-rules", type=Path, required=True)
    parser.add_argument("--license", type=Path, required=True)
    parser.add_argument("--third-party-licenses", type=Path, required=True)
    parser.add_argument("--notices", type=Path, required=True)
    parser.add_argument("--artifact-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_native_entries(contract: dict) -> dict[str, Path]:
    return {
        f"jni/{abi}/{library}": Path(abi) / library
        for library, abis in contract["nativeLibraries"].items()
        for abi in abis
    }


def read_api_entries(api_aar: Path) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(api_aar) as archive:
        for info in archive.infolist():
            name = info.filename.rstrip("/")
            if not name or info.is_dir():
                continue
            if name.startswith("jni/") or name.endswith(".so"):
                raise ValueError(f"Pure API AAR contains native code: {name}")
            if name in REPLACED_API_ENTRIES:
                continue
            if name in entries:
                raise ValueError(f"Duplicate API AAR entry: {name}")
            entries[name] = archive.read(info)
    for required in ("AndroidManifest.xml", "classes.jar"):
        if required not in entries:
            raise ValueError(f"Pure API AAR is missing {required}.")
    return entries


def read_native_entries(
    native_dir: Path,
    expected: dict[str, Path],
) -> dict[str, bytes]:
    actual_files = {
        path.relative_to(native_dir).as_posix(): path
        for path in native_dir.rglob("*.so")
        if path.is_file()
    }
    expected_files = {path.as_posix() for path in expected.values()}
    missing = sorted(expected_files - actual_files.keys())
    extra = sorted(actual_files.keys() - expected_files)
    if missing:
        raise ValueError(f"Missing native libraries: {', '.join(missing)}")
    if extra:
        raise ValueError(f"Unexpected native libraries: {', '.join(extra)}")
    return {
        archive_name: actual_files[relative.as_posix()].read_bytes()
        for archive_name, relative in expected.items()
    }


def build_manifest(
    artifact_version: str,
    contract: dict,
    source_lock: dict,
    entries: dict[str, bytes],
) -> dict:
    components = {
        name: {
            "bytes": len(data),
            "sha256": sha256_bytes(data),
        }
        for name, data in sorted(entries.items())
        if name == "classes.jar" or name.startswith("jni/")
    }
    return {
        "schemaVersion": 1,
        "artifact": {
            "group": contract["artifact"]["group"],
            "name": contract["artifact"]["name"],
            "version": artifact_version,
            "minSdk": contract["artifact"]["minSdk"],
            "jvmTarget": contract["artifact"]["jvmTarget"],
        },
        "liteRt": source_lock["liteRt"],
        "patchSeries": source_lock["patchSeries"],
        "components": components,
    }


def main() -> int:
    args = parse_args()
    api_aar = args.api_aar.resolve()
    native_dir = args.native_dir.resolve()
    contract = read_json(args.contract.resolve())
    source_lock = read_json(args.source_lock.resolve())

    entries = read_api_entries(api_aar)
    entries.update(
        read_native_entries(native_dir, expected_native_entries(contract))
    )
    entries["consumer-rules.pro"] = args.consumer_rules.read_bytes()
    entries["META-INF/LICENSE-LiteRT.txt"] = args.license.read_bytes()
    entries["META-INF/THIRD_PARTY_LICENSES.txt"] = (
        args.third_party_licenses.read_bytes()
    )
    entries["META-INF/THIRD_PARTY_NOTICES.md"] = args.notices.read_bytes()

    manifest = build_manifest(
        args.artifact_version,
        contract,
        source_lock,
        entries,
    )
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    entries["META-INF/bss-litert-build.json"] = manifest_bytes

    output = args.output.resolve()
    write_archive(output, entries)
    manifest_output = args.manifest_output.resolve()
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_bytes(manifest_bytes)
    print(f"Complete AAR: {output}")
    print(f"Build manifest: {manifest_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
