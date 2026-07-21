#!/usr/bin/env python3
"""Create deterministic LiteRT x86 release artifacts and metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-library", type=Path, required=True)
    parser.add_argument("--source-license", type=Path, required=True)
    parser.add_argument("--third-party-licenses", type=Path, required=True)
    parser.add_argument("--notices", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--artifact-version", required=True)
    parser.add_argument("--litert-version", required=True)
    parser.add_argument("--litert-commit", required=True)
    parser.add_argument("--bazel-version", required=True)
    parser.add_argument("--ndk-version", required=True)
    parser.add_argument("--android-api-level", type=int, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_zip_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    args = parse_args()
    dist_dir = args.dist_dir.resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)

    binary_name = f"libLiteRt-{args.artifact_version}-android-x86.so"
    aar_name = f"litert-{args.artifact_version}-android-x86.aar"
    binary_path = dist_dir / binary_name
    aar_path = dist_dir / aar_name
    source_license_path = dist_dir / "LICENSE-LiteRT.txt"
    third_party_path = dist_dir / "THIRD_PARTY_LICENSES.txt"
    notices_path = dist_dir / "THIRD_PARTY_NOTICES.md"
    validation_path = dist_dir / args.validation_report.name

    if args.shared_library.resolve() != binary_path:
        shutil.copyfile(args.shared_library, binary_path)
    shutil.copyfile(args.source_license, source_license_path)
    shutil.copyfile(args.third_party_licenses, third_party_path)
    shutil.copyfile(args.notices, notices_path)
    shutil.copyfile(args.validation_report, validation_path)

    manifest = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    package="io.github.wluhwluh.bss.litert.x86" />\n'
    ).encode("utf-8")
    with zipfile.ZipFile(aar_path, "w") as archive:
        write_zip_entry(archive, "AndroidManifest.xml", manifest)
        write_zip_entry(archive, "LICENSE", source_license_path.read_bytes())
        write_zip_entry(archive, "THIRD_PARTY_LICENSES.txt", third_party_path.read_bytes())
        write_zip_entry(archive, "THIRD_PARTY_NOTICES.md", notices_path.read_bytes())
        write_zip_entry(archive, "jni/x86/libLiteRt.so", binary_path.read_bytes())

    manifest_path = dist_dir / "build-manifest.json"
    build_manifest = {
        "schemaVersion": 1,
        "artifactVersion": args.artifact_version,
        "litert": {
            "version": args.litert_version,
            "commit": args.litert_commit,
            "repository": "https://github.com/google-ai-edge/LiteRT",
        },
        "toolchain": {
            "bazel": args.bazel_version,
            "androidNdk": args.ndk_version,
            "androidApiLevel": args.android_api_level,
            "rulesAndroidNdk": "0.1.3",
        },
        "build": {
            "target": "//litert/kotlin:LiteRt",
            "abi": "x86",
            "buildInclude": "cpu_only",
            "disabledXnnpackMicrokernels": [
                "avxvnni",
                "avxvnniint8",
                "avx512fp16",
                "avx512amx",
            ],
        },
        "outputs": {
            binary_name: {"bytes": binary_path.stat().st_size, "sha256": sha256(binary_path)},
            aar_name: {"bytes": aar_path.stat().st_size, "sha256": sha256(aar_path)},
        },
        "expectedDynamicDependencies": [
            "libandroid.so",
            "libc.so",
            "libdl.so",
            "liblog.so",
            "libm.so",
        ],
    }
    manifest_path.write_text(
        json.dumps(build_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(json.dumps(build_manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
