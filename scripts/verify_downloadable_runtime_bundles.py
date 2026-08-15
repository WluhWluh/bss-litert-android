#!/usr/bin/env python3
"""Verify downloadable LiteRT bundles and their immutable release index."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from build_downloadable_runtime_bundles import (
    common_manifest,
    cpu_file_manifest,
    json_bytes,
    native_file_manifest,
    sha256_bytes,
    sha256_file,
)
from deterministic_archive import FIXED_ZIP_TIME, write_archive
from verify_downloadable_api import verify as verify_explicit_loader_api


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = REPO_ROOT / "contracts/downloadable-runtime-contract.json"
DEFAULT_API_SOURCE_LOCK = REPO_ROOT / "config/downloadable-api-source-lock.json"
DEFAULT_DIST = REPO_ROOT / "dist/downloadable-runtime"


def read_normalized_archive(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError(f"Archive entries are not unique and sorted: {path.name}")
        for info in infos:
            if info.date_time != FIXED_ZIP_TIME:
                raise ValueError(
                    f"Archive timestamp is not normalized: {path.name}/{info.filename}"
                )
            if info.external_attr >> 16 != 0o100644:
                raise ValueError(
                    f"Archive mode is not normalized: {path.name}/{info.filename}"
                )
        return {info.filename: archive.read(info) for info in infos}


def require_file(path: Path, size: int, sha256: str) -> None:
    if not path.is_file() or path.stat().st_size != size or sha256_file(path) != sha256:
        raise ValueError(f"Release asset identity mismatch: {path.name}")


def verify_elf(data: bytes, metadata: dict, readelf: str, label: str) -> None:
    with tempfile.TemporaryDirectory(prefix="bss-litert-elf-") as directory:
        library = Path(directory) / metadata["path"]
        library.write_bytes(data)
        result = subprocess.run(
            [readelf, "-h", "-d", "-lW", str(library)],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise ValueError(f"readelf failed for {label}: {result.stderr.strip()}")
    output = result.stdout
    elf_class = re.search(r"^\s*Class:\s+(\S+)", output, re.MULTILINE)
    machine = re.search(r"^\s*Machine:\s+(.+?)\s*$", output, re.MULTILINE)
    machine_names = {
        "AArch64": "EM_AARCH64",
        "ARM": "EM_ARM",
        "Advanced Micro Devices X86-64": "EM_X86_64",
        "Intel 80386": "EM_386",
    }
    if elf_class is None or elf_class.group(1) != metadata["elfClass"]:
        raise ValueError(f"ELF class differs from the contract: {label}")
    if machine is None or machine_names.get(machine.group(1)) != metadata["machine"]:
        raise ValueError(f"ELF machine differs from the contract: {label}")

    needed = re.findall(r"\(NEEDED\).*?\[(.+?)\]", output)
    if needed != metadata["needed"]:
        raise ValueError(f"ELF DT_NEEDED differs from the contract: {label}")
    sonames = re.findall(r"\(SONAME\).*?\[(.+?)\]", output)
    if sonames != [metadata["soname"]]:
        raise ValueError(f"ELF SONAME differs from the contract: {label}")
    alignments = [
        int(value, 16)
        for value in re.findall(r"^\s*LOAD\s+.*?\s(0x[0-9a-fA-F]+)\s*$", output, re.MULTILINE)
    ]
    if not alignments or any(value != metadata["loadAlignment"] for value in alignments):
        raise ValueError(f"ELF LOAD alignment differs from the contract: {label}")
    for runtime_load in metadata.get("runtimeLoads", []):
        if runtime_load.encode("ascii") not in data or b"dlopen" not in data:
            raise ValueError(f"ELF runtime load is not evidenced in the binary: {label}")


def verify_api_aar(
    path: Path,
    contract: dict,
    contract_bytes: bytes,
    source_lock_path: Path,
    source_lock_bytes: bytes,
) -> None:
    entries = read_normalized_archive(path)
    if any(name.startswith("jni/") for name in entries):
        raise ValueError("Pure API AAR contains native libraries")
    metadata = contract["apiAar"]
    if entries.get(metadata["embeddedContractPath"]) != contract_bytes:
        raise ValueError("Pure API AAR does not contain the exact downloadable contract")
    if entries.get(metadata["embeddedSourceLockPath"]) != source_lock_bytes:
        raise ValueError("Pure API AAR does not contain the exact API source lock")
    if "META-INF/bss-litert/bounded-gpu-runtime-contract.json" in entries:
        raise ValueError("Pure API AAR retained the packaged-runtime contract")
    classes = entries.get("classes.jar")
    if classes is None:
        raise ValueError("Pure API AAR has no classes.jar")
    if len(classes) != metadata["classesJarByteSize"]:
        raise ValueError("Pure API AAR classes.jar size mismatch")
    if sha256_bytes(classes) != metadata["classesJarSha256"]:
        raise ValueError("Pure API AAR classes.jar identity mismatch")

    with tempfile.TemporaryDirectory(prefix="bss-litert-release-api-") as directory:
        base_aar = Path(directory) / metadata["baseFileName"]
        write_archive(
            base_aar,
            {
                "AndroidManifest.xml": entries["AndroidManifest.xml"],
                "classes.jar": classes,
            },
        )
        verify_explicit_loader_api(
            base_aar,
            source_lock_path,
            verify_output_identity=False,
        )


def verify_cpu_bundle(
    path: Path,
    abi: str,
    metadata: dict,
    contract: dict,
    readelf: str,
) -> None:
    entries = read_normalized_archive(path)
    expected_names = {"manifest.json"} | {
        file_metadata["path"] for file_metadata in metadata["files"]
    }
    if set(entries) != expected_names:
        raise ValueError(f"Unexpected CPU bundle entries: {path.name}")
    for file_metadata in metadata["files"]:
        library = entries[file_metadata["path"]]
        if (
            len(library) != file_metadata["byteSize"]
            or sha256_bytes(library) != file_metadata["sha256"]
        ):
            raise ValueError(
                f"CPU library identity mismatch: {abi}/{file_metadata['path']}"
            )
        verify_elf(
            library,
            file_metadata,
            readelf,
            f"{abi}/{file_metadata['path']}",
        )

    cpu = contract["cpuCore"]
    expected_manifest = common_manifest(
        contract,
        "cpu-core",
        abi,
        cpu["componentManifestSchemaVersion"],
    )
    expected_manifest["capabilities"] = ["cpu"]
    expected_manifest["loadOrder"] = cpu["loadOrder"]
    expected_manifest["files"] = [
        cpu_file_manifest(contract, abi, file_metadata)
        for file_metadata in metadata["files"]
    ]
    manifest = json.loads(entries["manifest.json"])
    if manifest != expected_manifest:
        raise ValueError(f"CPU manifest contract mismatch: {abi}")
    if entries["manifest.json"] != json_bytes(manifest):
        raise ValueError(f"CPU manifest is not canonical JSON: {abi}")


def verify_gpu_bundle(path: Path, contract: dict, readelf: str) -> None:
    metadata = contract["boundedGpu"]
    entries = read_normalized_archive(path)
    expected_names = {"manifest.json"} | {
        file_metadata["path"] for file_metadata in metadata["files"]
    }
    if set(entries) != expected_names:
        raise ValueError("Unexpected bounded GPU bundle entries")
    for file_metadata in metadata["files"]:
        library = entries[file_metadata["path"]]
        if (
            len(library) != file_metadata["byteSize"]
            or sha256_bytes(library) != file_metadata["sha256"]
        ):
            raise ValueError(f"GPU library identity mismatch: {file_metadata['path']}")
        verify_elf(library, file_metadata, readelf, file_metadata["path"])

    expected_manifest = common_manifest(
        contract,
        "bounded-gpu",
        metadata["abi"],
        metadata["componentManifestSchemaVersion"],
    )
    expected_manifest["capabilities"] = ["gpu-opencl-bounded-fp32"]
    expected_manifest["requiredCore"] = metadata["requiredCore"]
    expected_manifest["profile"] = metadata["profile"]
    expected_manifest["files"] = [
        native_file_manifest(file_metadata) for file_metadata in metadata["files"]
    ]
    manifest = json.loads(entries["manifest.json"])
    if manifest != expected_manifest:
        raise ValueError("Bounded GPU manifest contract mismatch")
    if entries["manifest.json"] != json_bytes(manifest):
        raise ValueError("Bounded GPU manifest is not canonical JSON")


def verify_checksums(dist: Path, expected_names: set[str]) -> None:
    actual_names = {path.name for path in dist.iterdir() if path.is_file()}
    if actual_names != expected_names | {"SHA256SUMS"}:
        raise ValueError("Release directory contains an unexpected asset set")
    lines = (dist / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    expected = {
        path.name: sha256_file(path)
        for path in dist.iterdir()
        if path.is_file() and path.name != "SHA256SUMS"
    }
    actual = {}
    for line in lines:
        digest, name = line.split("  ", 1)
        if name in actual:
            raise ValueError(f"Duplicate checksum entry: {name}")
        actual[name] = digest
    if actual != expected:
        raise ValueError("SHA256SUMS does not cover the exact release assets")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--api-source-lock",
        type=Path,
        default=DEFAULT_API_SOURCE_LOCK,
    )
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument(
        "--readelf",
        default=shutil.which("llvm-readelf") or shutil.which("readelf"),
    )
    args = parser.parse_args()
    if not args.readelf:
        parser.error("llvm-readelf or readelf is required")
    contract_bytes = args.contract.read_bytes()
    contract = json.loads(contract_bytes)
    source_lock_path = args.api_source_lock.resolve()
    source_lock_bytes = source_lock_path.read_bytes()
    dist = args.dist.resolve()
    index_bytes = (dist / "downloadable-runtime-index.json").read_bytes()
    index = json.loads(index_bytes)
    if index_bytes != json_bytes(index):
        raise ValueError("Release index is not canonical JSON")
    if (
        index["schemaVersion"] != 2
        or index["contractSchemaVersion"] != contract["schemaVersion"]
        or index["releaseVersion"] != contract["releaseVersion"]
        or index["releaseTag"] != contract["releaseTag"]
        or index["runtimeArtifactVersion"] != contract["runtimeArtifactVersion"]
        or index["sourceAar"] != contract["sourceAar"]
    ):
        raise ValueError("Release index identity differs from the contract")

    api_metadata = index["apiAar"]
    api_path = dist / api_metadata["fileName"]
    require_file(api_path, api_metadata["byteSize"], api_metadata["sha256"])
    verify_api_aar(
        api_path,
        contract,
        contract_bytes,
        source_lock_path,
        source_lock_bytes,
    )

    lock_metadata = index["apiSourceLock"]
    lock_path = dist / lock_metadata["fileName"]
    require_file(lock_path, lock_metadata["byteSize"], lock_metadata["sha256"])
    if lock_path.read_bytes() != source_lock_bytes:
        raise ValueError("Release API source lock differs from the source lock")

    indexed = {(value["component"], value["abi"]): value for value in index["bundles"]}
    expected_keys = {
        ("cpu-core", abi) for abi in contract["cpuCore"]["abis"]
    } | {("bounded-gpu", contract["boundedGpu"]["abi"])}
    if set(indexed) != expected_keys or len(indexed) != len(index["bundles"]):
        raise ValueError("Release index contains an unexpected component set")

    bundle_names = set()
    for abi, metadata in contract["cpuCore"]["abis"].items():
        record = indexed[("cpu-core", abi)]
        path = dist / metadata["bundleFileName"]
        if path.name != record["fileName"]:
            raise ValueError(f"CPU index file name mismatch: {abi}")
        require_file(path, record["byteSize"], record["sha256"])
        verify_cpu_bundle(path, abi, metadata, contract, args.readelf)
        if record["manifestSha256"] != sha256_bytes(
            read_normalized_archive(path)["manifest.json"]
        ):
            raise ValueError(f"CPU index manifest hash mismatch: {abi}")
        bundle_names.add(path.name)

    gpu = contract["boundedGpu"]
    record = indexed[("bounded-gpu", gpu["abi"])]
    gpu_path = dist / gpu["bundleFileName"]
    if gpu_path.name != record["fileName"]:
        raise ValueError("GPU index file name mismatch")
    require_file(gpu_path, record["byteSize"], record["sha256"])
    verify_gpu_bundle(gpu_path, contract, args.readelf)
    if record["manifestSha256"] != sha256_bytes(
        read_normalized_archive(gpu_path)["manifest.json"]
    ):
        raise ValueError("GPU index manifest hash mismatch")
    bundle_names.add(gpu_path.name)

    if (dist / "downloadable-runtime-contract.json").read_bytes() != contract_bytes:
        raise ValueError("Release contract differs from the source contract")
    expected_assets = bundle_names | {
        api_path.name,
        "downloadable-api-source-lock.json",
        "downloadable-runtime-contract.json",
        "downloadable-runtime-index.json",
        "LICENSE-LiteRT.txt",
        "THIRD_PARTY_NOTICE-LiteRT.txt",
    }
    verify_checksums(dist, expected_assets)
    print(f"Verified {index['releaseVersion']} with {len(index['bundles'])} bundles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
