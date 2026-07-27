#!/usr/bin/env python3
"""Verify the immutable identity and archive contract of a bounded-GPU AAR."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aar", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
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
    if "jni/x86_64/libLiteRtClGlAccelerator.so" in entries:
        raise ValueError("The unbounded x86_64 GPU accelerator must not be packaged")
    if any(name.endswith("libOCLQ.so") for name in entries):
        raise ValueError("The diagnostic OpenCL shim must not be packaged")

    classes, class_infos = archive_entries(entries["classes.jar"])
    verify_normalized(class_infos, "classes.jar")
    expected_classes = {
        f"{CAPABILITY_CLASS_PREFIX}.class",
        f"{CAPABILITY_CLASS_PREFIX}$Capability.class",
    }
    if not expected_classes.issubset(classes):
        raise ValueError("The stable bounded-runtime capability API is missing")

    accelerator = entries["jni/arm64-v8a/libLiteRtClGlAccelerator.so"]
    if accelerator.count(b"libBssOcl.so") != 1 or b"libOpenCL.so" in accelerator:
        raise ValueError("The arm64 accelerator does not use the bounded shim")
    shim = entries["jni/arm64-v8a/libBssOcl.so"]
    for marker in (
        b"2.1.5-bss.2",
        b"gpu-opencl-bounded-fp32-v1",
        b"nativeGetCapabilitySchemaVersion",
        b"nativeGetEventWaitCount",
    ):
        if marker not in shim:
            raise ValueError(f"Bounded shim marker is missing: {marker!r}")

    if manifest["coordinate"] != contract["coordinate"]:
        raise ValueError("Build manifest coordinate differs from the contract")
    if manifest["contractSha256"] != sha256(contract_bytes):
        raise ValueError("Build manifest contract hash is incorrect")
    if manifest["aar"]["sha256"] != sha256(aar_bytes):
        raise ValueError("Build manifest AAR hash is incorrect")
    if manifest["capability"] != contract["capability"]:
        raise ValueError("Build manifest capability differs from the contract")
    for name in expected_native:
        component = manifest["nativeComponents"].get(name)
        if component is None or component["sha256"] != sha256(entries[name]):
            raise ValueError(f"Native component hash is incorrect: {name}")

    print(f"Verified {contract['coordinate']}")
    print(f"AAR SHA-256: {sha256(aar_bytes)}")


if __name__ == "__main__":
    main()
