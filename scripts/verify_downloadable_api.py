#!/usr/bin/env python3
"""Verify the source-built classes-only API and explicit loader routing."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO_ROOT / "config/downloadable-api-source-lock.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_archive(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        entries = {info.filename: archive.read(info) for info in infos}
    if len(entries) != len(infos):
        raise ValueError(f"Archive contains duplicate entries: {path}")
    return entries


def class_entry(class_name: str) -> str:
    return class_name.replace(".", "/") + ".class"


def javap(classes_jar: Path, *args: str) -> str:
    result = subprocess.run(
        ["javap", "-classpath", str(classes_jar), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def verify(aar: Path, lock_path: Path) -> None:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    expected = lock["output"]
    actual_aar_size = aar.stat().st_size
    actual_aar_sha256 = sha256_file(aar)
    if actual_aar_size != expected["baseAarByteSize"]:
        raise ValueError(
            "Explicit-loader base AAR size differs from the lock: "
            f"{actual_aar_size} != {expected['baseAarByteSize']}; "
            f"actual SHA-256 {actual_aar_sha256}"
        )
    if actual_aar_sha256 != expected["baseAarSha256"]:
        raise ValueError(
            "Explicit-loader base AAR SHA-256 differs from the lock: "
            f"{actual_aar_sha256} != {expected['baseAarSha256']}"
        )

    aar_entries = read_archive(aar)
    if set(aar_entries) != {"AndroidManifest.xml", "classes.jar"}:
        raise ValueError(f"Unexpected base AAR entries: {sorted(aar_entries)}")
    classes = aar_entries["classes.jar"]
    if len(classes) != expected["classesJarByteSize"]:
        raise ValueError(
            "Explicit-loader classes JAR size differs from the lock: "
            f"{len(classes)} != {expected['classesJarByteSize']}; "
            f"actual SHA-256 {sha256_bytes(classes)}"
        )
    actual_classes_sha256 = sha256_bytes(classes)
    if actual_classes_sha256 != expected["classesJarSha256"]:
        raise ValueError(
            "Explicit-loader classes JAR SHA-256 differs from the lock: "
            f"{actual_classes_sha256} != {expected['classesJarSha256']}"
        )

    with tempfile.TemporaryDirectory(prefix="bss-litert-loader-api-") as directory:
        classes_jar = Path(directory) / "classes.jar"
        classes_jar.write_bytes(classes)
        class_entries = read_archive(classes_jar)
        expected_major = expected["jvmClassMajor"]
        for name, data in sorted(class_entries.items()):
            if not name.endswith(".class"):
                continue
            if len(data) < 8 or data[:4] != b"\xca\xfe\xba\xbe":
                raise ValueError(f"Invalid JVM class file: {name}")
            actual_major = struct.unpack(">H", data[6:8])[0]
            if actual_major != expected_major:
                raise ValueError(
                    f"Unexpected JVM class major for {name}: "
                    f"{actual_major} != {expected_major}"
                )

        loader = lock["loaderApi"]
        loader_entry = class_entry(loader["className"])
        if loader_entry not in class_entries:
            raise ValueError(f"Explicit loader class is missing: {loader_entry}")
        for prefix in loader["forbiddenClassPrefixes"]:
            if any(name.startswith(prefix) for name in class_entries):
                raise ValueError(f"Forbidden API class prefix is packaged: {prefix}")

        loader_api = " ".join(javap(classes_jar, "-public", loader["className"]).split())
        for member in (loader["configureMethod"], loader["loadMethod"]):
            if member not in loader_api:
                raise ValueError(f"Explicit loader API member is missing: {member}")

        loader_bytecode = javap(classes_jar, "-c", "-p", loader["className"])
        if "java/lang/System.loadLibrary" not in loader_bytecode:
            raise ValueError("Packaged-library fallback is missing from the loader")
        if "java/lang/System.load:" not in loader_bytecode:
            raise ValueError("Absolute-path System.load is missing from the loader")

        for class_name in loader["routedClasses"]:
            bytecode = javap(classes_jar, "-c", "-p", class_name)
            if "LiteRtNativeLibraryLoader.load:()V" not in bytecode:
                raise ValueError(f"Native initialization is not routed: {class_name}")
            if "java/lang/System.loadLibrary" in bytecode:
                raise ValueError(f"Direct System.loadLibrary remains in {class_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aar", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    args = parser.parse_args()
    verify(args.aar.resolve(), args.lock.resolve())
    print(f"Verified explicit-loader API: {args.aar.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
