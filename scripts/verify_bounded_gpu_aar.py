#!/usr/bin/env python3
"""Verify the immutable identity and archive contract of a bounded-GPU AAR."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
CAPABILITY_CLASS_PREFIX = "io/github/wluhwluh/bss/litert/BssLiteRtRuntime"
CONTRACT_ENTRY = "META-INF/bss-litert/bounded-gpu-runtime-contract.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_entries(data: bytes) -> tuple[dict[str, bytes], list[zipfile.ZipInfo]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        entries = {info.filename: archive.read(info) for info in infos}
    if len(entries) != len(infos):
        raise ValueError("Archive contains duplicate entries")
    return entries, infos


def expected_native_entries(contract: dict) -> set[str]:
    return {
        f"jni/{abi}/{library}"
        for abi, libraries in contract["nativeMatrix"].items()
        for library in libraries
    }


def verify_normalized(infos: list[zipfile.ZipInfo], label: str) -> None:
    names = [info.filename for info in infos]
    if names != sorted(names):
        raise ValueError(f"{label} entries are not sorted")
    for info in infos:
        if info.date_time != FIXED_ZIP_TIME:
            raise ValueError(f"{label} timestamp is not normalized: {info.filename}")
        if info.external_attr >> 16 != 0o100644:
            raise ValueError(f"{label} mode is not normalized: {info.filename}")


def verify_arm64_page_alignment(
    entries: dict[str, bytes], readelf: Path
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, data in entries.items():
            if not name.startswith("jni/arm64-v8a/") or not name.endswith(".so"):
                continue
            library = root / Path(name).name
            library.write_bytes(data)
            result = subprocess.run(
                [str(readelf), "-lW", str(library)],
                check=True,
                capture_output=True,
                text=True,
            )
            alignments = [
                int(line.split()[-1], 16)
                for line in result.stdout.splitlines()
                if line.lstrip().startswith("LOAD ")
            ]
            if not alignments or min(alignments) < 0x4000:
                raise ValueError(f"Arm64 LOAD alignment is below 16 KiB: {name}")


def verify_x86_native_contract(
    entries: dict[str, bytes], readelf: Path, android_min_api: int
) -> None:
    expected_sonames = {
        "jni/x86/libLiteRt.so": "libLiteRt.so",
        "jni/x86/liblitert_jni.so": "liblitert_jni.so",
    }
    expected_api_bytes = f"{android_min_api:02x} 00 00 00"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, expected_soname in expected_sonames.items():
            library = root / Path(name).name
            library.write_bytes(entries[name])
            dynamic = subprocess.run(
                [str(readelf), "-d", str(library)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            if f"Library soname: [{expected_soname}]" not in dynamic:
                raise ValueError(f"Unexpected x86 SONAME: {name}")

            program_headers = subprocess.run(
                [str(readelf), "-lW", str(library)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            alignments = [
                int(line.split()[-1], 16)
                for line in program_headers.splitlines()
                if line.lstrip().startswith("LOAD ")
            ]
            if not alignments or min(alignments) < 0x4000:
                raise ValueError(f"x86 LOAD alignment is below 16 KiB: {name}")

            notes = subprocess.run(
                [str(readelf), "--notes", str(library)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            if (
                ".note.android.ident" not in notes
                or f"description data: {expected_api_bytes}" not in notes
            ):
                raise ValueError(
                    f"x86 Android API note is not {android_min_api}: {name}"
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aar", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--readelf", type=Path)
    args = parser.parse_args()

    aar_bytes = args.aar.read_bytes()
    contract_bytes = args.contract.read_bytes()
    contract = json.loads(contract_bytes)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries, infos = archive_entries(aar_bytes)
    verify_normalized(infos, "AAR")

    if entries.get(CONTRACT_ENTRY) != contract_bytes:
        raise ValueError("Embedded runtime contract differs from the release contract")
    actual_native = {name for name in entries if name.startswith("jni/")}
    expected_native = expected_native_entries(contract)
    if actual_native != expected_native:
        raise ValueError("AAR native matrix differs from the runtime contract")
    for abi in ("armeabi-v7a", "x86_64", "x86"):
        if f"jni/{abi}/libLiteRtClGlAccelerator.so" in entries:
            raise ValueError(f"The unbounded {abi} GPU accelerator must not be packaged")
    if any(name.endswith("libOCLQ.so") for name in entries):
        raise ValueError("The diagnostic OpenCL shim must not be packaged")

    classes, class_infos = archive_entries(entries["classes.jar"])
    verify_normalized(class_infos, "classes.jar")
    required_classes = {
        f"{CAPABILITY_CLASS_PREFIX}.class",
        f"{CAPABILITY_CLASS_PREFIX}$Capability.class",
        "com/google/ai/edge/litert/CompiledModel.class",
        "com/google/ai/edge/litert/Environment.class",
        "org/tensorflow/lite/Interpreter.class",
    }
    missing_classes = required_classes - set(classes)
    if missing_classes:
        raise ValueError(f"Combined LiteRT class set is incomplete: {missing_classes}")

    accelerator = entries["jni/arm64-v8a/libLiteRtClGlAccelerator.so"]
    if accelerator.count(b"libBssOcl.so") != 1 or b"libOpenCL.so" in accelerator:
        raise ValueError("The arm64 accelerator does not use the bounded shim")
    shim = entries["jni/arm64-v8a/libBssOcl.so"]
    for marker in (
        contract["capability"]["artifactVersion"].encode(),
        contract["capability"]["profileId"].encode(),
        b"nativeGetCapabilitySchemaVersion",
        b"nativeGetEventWaitCount",
    ):
        if marker not in shim:
            raise ValueError(f"Bounded shim marker is missing: {marker!r}")
    custom_jni = entries["jni/arm64-v8a/liblitert_jni.so"]
    if b"Failed to set Booming SS bounded GPU kernelBatchSize." not in custom_jni:
        raise ValueError("The source-built bounded GPU JNI marker is missing")

    if manifest["coordinate"] != contract["coordinate"]:
        raise ValueError("Build manifest coordinate differs from the contract")
    if manifest["contractSha256"] != sha256(contract_bytes):
        raise ValueError("Build manifest contract hash is incorrect")
    if manifest["aar"]["sha256"] != sha256(aar_bytes):
        raise ValueError("Build manifest AAR hash is incorrect")
    if manifest["capability"] != contract["capability"]:
        raise ValueError("Build manifest capability differs from the contract")
    if manifest["sourceBuild"]["outputSha256"] != sha256(custom_jni):
        raise ValueError("Source-built JNI hash is incorrect")
    for name in expected_native:
        component = manifest["nativeComponents"].get(name)
        if component is None or component["sha256"] != sha256(entries[name]):
            raise ValueError(f"Native component hash is incorrect: {name}")

    if args.readelf is not None:
        verify_arm64_page_alignment(entries, args.readelf)
        verify_x86_native_contract(
            entries, args.readelf, contract["androidMinApi"]
        )

    print(f"Verified {contract['coordinate']}")
    print(f"AAR SHA-256: {sha256(aar_bytes)}")


if __name__ == "__main__":
    main()
