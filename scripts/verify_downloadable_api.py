#!/usr/bin/env python3
"""Verify the source-built classes-only API and split explicit loader routing."""

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


def output_identity(aar: Path, entries: dict[str, bytes]) -> dict[str, int | str]:
    classes = entries["classes.jar"]
    return {
        "baseAarByteSize": aar.stat().st_size,
        "baseAarSha256": sha256_file(aar),
        "classesJarByteSize": len(classes),
        "classesJarSha256": sha256_bytes(classes),
    }


def verify(
    aar: Path,
    lock_path: Path,
    verify_output_identity: bool = True,
) -> None:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    expected = lock["output"]
    aar_entries = read_archive(aar)
    if set(aar_entries) != {"AndroidManifest.xml", "classes.jar"}:
        raise ValueError(f"Unexpected base AAR entries: {sorted(aar_entries)}")
    manifest = aar_entries["AndroidManifest.xml"]
    for forbidden in (b"FOREGROUND_SERVICE", b"android.hardware.npu"):
        if forbidden in manifest:
            raise ValueError(f"Downloadable API manifest contains {forbidden!r}")
    if b"libOpenCL.so" not in manifest:
        raise ValueError("Downloadable API manifest omits optional OpenCL visibility")

    actual_identity = output_identity(aar, aar_entries)
    if verify_output_identity and any(
        actual_identity[key] != expected[key] for key in actual_identity
    ):
        raise ValueError(
            "Explicit-loader output identity differs from the lock: "
            f"{json.dumps(actual_identity, sort_keys=True)}"
        )

    classes = aar_entries["classes.jar"]
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
        for member in (
            loader["configureMethod"],
            loader["loadMethod"],
            loader["configuredJniMethod"],
        ):
            if member not in loader_api:
                raise ValueError(f"Explicit loader API member is missing: {member}")

        constants = javap(classes_jar, "-constants", "-p", loader["className"])
        for value in (
            loader["runtimeFileName"],
            loader["jniFileName"],
            loader["packagedFallbackLibraryName"],
        ):
            if f'"{value}"' not in constants:
                raise ValueError(f"Explicit loader constant is missing: {value}")

        loader_bytecode = javap(classes_jar, "-c", "-p", loader["className"])
        if loader_bytecode.count("java/lang/System.loadLibrary:") != 1:
            raise ValueError("Packaged JNI-library fallback is not unique")
        if loader_bytecode.count("java/lang/System.load:") != 2:
            raise ValueError("Explicit runtime/JNI loading does not contain exactly two loads")
        bytecode_lines = loader_bytecode.splitlines()
        load_lines = [
            index
            for index, line in enumerate(bytecode_lines)
            if "java/lang/System.load:(Ljava/lang/String;)V" in line
        ]
        operands = [
            bytecode_lines[index - 1].split(":", 1)[1].strip()
            for index in load_lines
        ]
        if operands != ["aload_1", "aload_2"]:
            raise ValueError("Explicit bytecode load order is not runtime then sibling JNI")
        if "siblingJniPath:(Ljava/lang/String;)Ljava/lang/String;" not in loader_bytecode:
            raise ValueError("Explicit loader does not derive the sibling JNI path")

        for class_name in loader["routedClasses"]:
            bytecode = javap(classes_jar, "-c", "-p", class_name)
            if "LiteRtNativeLibraryLoader.load:()V" not in bytecode:
                raise ValueError(f"Native initialization is not routed: {class_name}")
            if "java/lang/System.loadLibrary" in bytecode or "java/lang/System.load:" in bytecode:
                raise ValueError(f"Direct System loading remains in {class_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aar", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    args = parser.parse_args()
    verify(args.aar.resolve(), args.lock.resolve())
    print(f"Verified explicit split-loader API: {args.aar.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
