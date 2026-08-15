#!/usr/bin/env python3
"""Assemble and describe the deterministic bounded-GPU LiteRT AAR."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from deterministic_archive import archive_bytes, write_archive  # noqa: E402


CAPABILITY_CLASS_PREFIX = "io/github/wluhwluh/bss/litert/BssLiteRtRuntime"
CONTRACT_ENTRY = "META-INF/bss-litert/bounded-gpu-runtime-contract.json"
GPU_OPTION_PATCH = (
    "patches/bounded-gpu-runtime/"
    "0001-map-command-buffer-option-to-kernel-batch.patch"
)
SOURCE_FILES = (
    "config/bounded-gpu-runtime.env",
    "contracts/bounded-gpu-runtime-contract.json",
    GPU_OPTION_PATCH,
    "runtime/bounded-gpu/java/io/github/wluhwluh/bss/litert/BssLiteRtRuntime.java",
    "runtime/bounded-gpu/opencl_queue_shim.c",
    "runtime/bounded-gpu/opencl_stub.c",
    "scripts/build-bounded-gpu-runtime.sh",
    "scripts/package_bounded_gpu_aar.py",
    "scripts/patch_bounded_gpu_accelerator.py",
    "scripts/verify_bounded_gpu_aar.py",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_archive(path: Path) -> dict[str, bytes]:
    return read_archive_bytes(path.read_bytes(), str(path))


def read_archive_bytes(data: bytes, label: str) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        entries = {info.filename: archive.read(info) for info in infos}
    if len(entries) != len(infos):
        raise ValueError(f"Archive contains duplicate entries: {label}")
    return entries


def merge_official_aars(
    implementation: dict[str, bytes], api: dict[str, bytes]
) -> dict[str, bytes]:
    entries = dict(implementation)
    implementation_classes = read_archive_bytes(
        entries["classes.jar"], "implementation classes.jar"
    )
    api_classes = read_archive_bytes(api["classes.jar"], "API classes.jar")
    api_classes.pop("META-INF/MANIFEST.MF", None)
    duplicate_classes = set(implementation_classes) & set(api_classes)
    if duplicate_classes:
        raise ValueError(
            "Official implementation/API classes overlap: "
            f"{sorted(duplicate_classes)}"
        )
    implementation_classes.update(api_classes)
    entries["classes.jar"] = archive_bytes(implementation_classes)

    for name, data in api.items():
        if name == "classes.jar":
            continue
        if name.startswith("jni/"):
            if name in entries:
                raise ValueError(f"Official native component overlaps: {name}")
            entries[name] = data
            continue
        if name not in entries:
            entries[name] = data
        elif entries[name] != data:
            raise ValueError(f"Official shared AAR entry differs: {name}")
    return entries


def expected_native_entries(contract: dict) -> set[str]:
    return {
        f"jni/{abi}/{library}"
        for abi, libraries in contract["nativeMatrix"].items()
        for library in libraries
    }


def repository_commit(source_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def source_hashes(source_root: Path) -> dict[str, str]:
    result = {}
    for relative in SOURCE_FILES:
        source = source_root / relative
        if not source.is_file():
            raise ValueError(f"Required source file is missing: {relative}")
        result[relative] = sha256(source.read_bytes())
    return result


def parse_patch_result(value: str, field_count: int, label: str) -> list[str]:
    fields = value.strip().split(":")
    if len(fields) != field_count or any(not field for field in fields):
        raise ValueError(f"Invalid {label} result: {value!r}")
    return fields


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--implementation-aar", type=Path, required=True)
    parser.add_argument("--api-aar", type=Path, required=True)
    parser.add_argument("--arm64-jni", type=Path, required=True)
    parser.add_argument("--arm64-accelerator", type=Path, required=True)
    parser.add_argument("--arm64-shim", type=Path, required=True)
    parser.add_argument("--x86-supplement", type=Path, required=True)
    parser.add_argument("--capability-classes", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--litert-source-commit", required=True)
    parser.add_argument("--accelerator-patch-result", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    contract_bytes = args.contract.read_bytes()
    contract = json.loads(contract_bytes)
    implementation_entries = read_archive(args.implementation_aar)
    api_entries = read_archive(args.api_aar)
    entries = merge_official_aars(implementation_entries, api_entries)

    classes_entries = read_archive_bytes(entries["classes.jar"], "classes.jar")
    compiled_classes = {
        path.relative_to(args.capability_classes).as_posix(): path.read_bytes()
        for path in args.capability_classes.rglob("*.class")
    }
    expected_classes = {
        f"{CAPABILITY_CLASS_PREFIX}.class",
        f"{CAPABILITY_CLASS_PREFIX}$Capability.class",
    }
    if set(compiled_classes) != expected_classes:
        raise ValueError(
            "Capability compilation produced an unexpected class set: "
            f"{sorted(compiled_classes)}"
        )
    duplicates = set(classes_entries) & set(compiled_classes)
    if duplicates:
        raise ValueError(f"Capability classes already exist: {sorted(duplicates)}")
    classes_entries.update(compiled_classes)
    entries["classes.jar"] = archive_bytes(classes_entries)

    x86_entries = read_archive(args.x86_supplement)
    expected_x86 = {
        "jni/x86/libLiteRt.so",
        "jni/x86/liblitert_jni.so",
    }
    actual_x86 = {name for name in x86_entries if name.startswith("jni/")}
    if actual_x86 != expected_x86:
        raise ValueError("x86 supplement does not contain the expected split pair")

    entries["jni/arm64-v8a/liblitert_jni.so"] = args.arm64_jni.read_bytes()
    entries["jni/arm64-v8a/libLiteRtClGlAccelerator.so"] = (
        args.arm64_accelerator.read_bytes()
    )
    entries["jni/arm64-v8a/libBssOcl.so"] = args.arm64_shim.read_bytes()
    for name in expected_x86:
        entries[name] = x86_entries[name]
    for removed in contract["removedOfficialComponents"]:
        entries.pop(removed, None)
    entries[CONTRACT_ENTRY] = contract_bytes

    actual_native = {name for name in entries if name.startswith("jni/")}
    expected_native = expected_native_entries(contract)
    if actual_native != expected_native:
        raise ValueError(
            "Packaged native matrix differs from the contract: "
            f"missing={sorted(expected_native - actual_native)}, "
            f"unexpected={sorted(actual_native - expected_native)}"
        )

    write_archive(args.output, entries)
    accelerator_patch = parse_patch_result(
        args.accelerator_patch_result, 2, "accelerator patch"
    )
    sources = source_hashes(args.source_root)
    native_components = {
        name: {
            "byteSize": len(entries[name]),
            "sha256": sha256(entries[name]),
        }
        for name in sorted(actual_native)
    }
    manifest = {
        "schemaVersion": "bss-litert-bounded-gpu-build-v2",
        "coordinate": contract["coordinate"],
        "baseLiteRtVersion": contract["baseLiteRtVersion"],
        "repositoryCommit": repository_commit(args.source_root),
        "contractSha256": sha256(contract_bytes),
        "inputArtifacts": {
            "officialImplementationAar": sha256(
                args.implementation_aar.read_bytes()
            ),
            "officialApiAar": sha256(args.api_aar.read_bytes()),
            "x86SupplementAar": sha256(args.x86_supplement.read_bytes()),
        },
        "sourceBuild": {
            "liteRtCommit": args.litert_source_commit,
            "target": "//litert/kotlin:litert_jni",
            "abi": "arm64-v8a",
            "patchSha256": sources[GPU_OPTION_PATCH],
            "outputSha256": sha256(args.arm64_jni.read_bytes()),
        },
        "transformations": {
            "gpuOptionMapping": {
                "sourceKey": "numStepsOfCommandBufferPreparations",
                "runtimeOption": "kernel_batch_size",
                "value": 1,
            },
            "openClLoader": {
                "offset": int(accelerator_patch[0]),
                "patchedSha256": accelerator_patch[1],
                "replacement": "libBssOcl.so",
            },
        },
        "capability": contract["capability"],
        "nativeComponents": native_components,
        "classesJar": {
            "byteSize": len(entries["classes.jar"]),
            "sha256": sha256(entries["classes.jar"]),
        },
        "sourceSha256": sources,
        "aar": {
            "fileName": args.output.name,
            "byteSize": args.output.stat().st_size,
            "sha256": sha256(args.output.read_bytes()),
        },
    }
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
