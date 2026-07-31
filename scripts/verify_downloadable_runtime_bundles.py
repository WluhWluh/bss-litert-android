#!/usr/bin/env python3
"""Verify downloadable LiteRT bundles and their immutable release index."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from build_downloadable_runtime_bundles import json_bytes, sha256_bytes, sha256_file
from deterministic_archive import FIXED_ZIP_TIME


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = REPO_ROOT / "contracts/downloadable-runtime-contract.json"
DEFAULT_DIST = REPO_ROOT / "dist/downloadable-runtime"


def read_normalized_archive(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError(f"Archive entries are not unique and sorted: {path.name}")
        for info in infos:
            if info.date_time != FIXED_ZIP_TIME:
                raise ValueError(f"Archive timestamp is not normalized: {path.name}/{info.filename}")
            if info.external_attr >> 16 != 0o100644:
                raise ValueError(f"Archive mode is not normalized: {path.name}/{info.filename}")
        return {info.filename: archive.read(info) for info in infos}


def require_file(path: Path, size: int, sha256: str) -> None:
    if not path.is_file() or path.stat().st_size != size or sha256_file(path) != sha256:
        raise ValueError(f"Release asset identity mismatch: {path.name}")


def verify_api_aar(path: Path, contract: dict, contract_bytes: bytes) -> None:
    entries = read_normalized_archive(path)
    if any(name.startswith("jni/") for name in entries):
        raise ValueError("Pure API AAR contains native libraries")
    embedded = contract["apiAar"]["embeddedContractPath"]
    if entries.get(embedded) != contract_bytes:
        raise ValueError("Pure API AAR does not contain the exact downloadable contract")
    if "META-INF/bss-litert/bounded-gpu-runtime-contract.json" in entries:
        raise ValueError("Pure API AAR retained the packaged-runtime contract")
    classes = entries.get("classes.jar")
    if classes is None or sha256_bytes(classes) != contract["sourceAar"]["classesJarSha256"]:
        raise ValueError("Pure API AAR classes.jar identity mismatch")


def verify_cpu_bundle(path: Path, abi: str, metadata: dict, contract: dict) -> None:
    entries = read_normalized_archive(path)
    library_name = contract["cpuCore"]["libraryName"]
    if set(entries) != {"manifest.json", library_name}:
        raise ValueError(f"Unexpected CPU bundle entries: {path.name}")
    library = entries[library_name]
    if len(library) != metadata["byteSize"] or sha256_bytes(library) != metadata["sha256"]:
        raise ValueError(f"CPU library identity mismatch: {abi}")
    manifest = json.loads(entries["manifest.json"])
    expected_needed = metadata.get(
        "systemDependenciesOverride",
        contract["cpuCore"]["systemDependencies"],
    )
    if manifest["component"] != "cpu-core" or manifest["abi"] != abi:
        raise ValueError(f"CPU manifest identity mismatch: {abi}")
    if manifest["files"] != [{
        "path": library_name,
        "byteSize": metadata["byteSize"],
        "sha256": metadata["sha256"],
        "elf": {
            "class": metadata["elfClass"],
            "machine": metadata["machine"],
            "soname": metadata["soname"],
            "needed": expected_needed,
        },
    }]:
        raise ValueError(f"CPU manifest file contract mismatch: {abi}")
    if entries["manifest.json"] != json_bytes(manifest):
        raise ValueError(f"CPU manifest is not canonical JSON: {abi}")


def verify_gpu_bundle(path: Path, contract: dict) -> None:
    metadata = contract["boundedGpu"]
    entries = read_normalized_archive(path)
    expected_names = {"manifest.json"} | {value["path"] for value in metadata["files"]}
    if set(entries) != expected_names:
        raise ValueError("Unexpected bounded GPU bundle entries")
    for file_metadata in metadata["files"]:
        library = entries[file_metadata["path"]]
        if (
            len(library) != file_metadata["byteSize"]
            or sha256_bytes(library) != file_metadata["sha256"]
        ):
            raise ValueError(f"GPU library identity mismatch: {file_metadata['path']}")
    manifest = json.loads(entries["manifest.json"])
    if manifest["component"] != "bounded-gpu" or manifest["abi"] != metadata["abi"]:
        raise ValueError("Bounded GPU manifest identity mismatch")
    if manifest["profile"] != metadata["profile"]:
        raise ValueError("Bounded GPU profile mismatch")
    if manifest["requiredCore"]["librarySha256"] != metadata["requiredCoreSha256"]:
        raise ValueError("Bounded GPU core dependency mismatch")
    if entries["manifest.json"] != json_bytes(manifest):
        raise ValueError("Bounded GPU manifest is not canonical JSON")


def verify_checksums(dist: Path) -> None:
    lines = (dist / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    expected = {
        path.name: sha256_file(path)
        for path in dist.iterdir()
        if path.is_file() and path.name != "SHA256SUMS"
    }
    actual = {}
    for line in lines:
        digest, name = line.split("  ", 1)
        actual[name] = digest
    if actual != expected:
        raise ValueError("SHA256SUMS does not cover the exact release assets")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    args = parser.parse_args()
    contract_bytes = args.contract.read_bytes()
    contract = json.loads(contract_bytes)
    dist = args.dist.resolve()
    index = json.loads((dist / "downloadable-runtime-index.json").read_text(encoding="utf-8"))

    api_metadata = index["apiAar"]
    api_path = dist / api_metadata["fileName"]
    require_file(api_path, api_metadata["byteSize"], api_metadata["sha256"])
    verify_api_aar(api_path, contract, contract_bytes)

    indexed = {(value["component"], value["abi"]): value for value in index["bundles"]}
    for abi, metadata in contract["cpuCore"]["abis"].items():
        record = indexed[("cpu-core", abi)]
        path = dist / metadata["bundleFileName"]
        if path.name != record["fileName"]:
            raise ValueError(f"CPU index file name mismatch: {abi}")
        require_file(path, record["byteSize"], record["sha256"])
        verify_cpu_bundle(path, abi, metadata, contract)

    gpu = contract["boundedGpu"]
    record = indexed[("bounded-gpu", gpu["abi"])]
    gpu_path = dist / gpu["bundleFileName"]
    require_file(gpu_path, record["byteSize"], record["sha256"])
    verify_gpu_bundle(gpu_path, contract)

    if (dist / "downloadable-runtime-contract.json").read_bytes() != contract_bytes:
        raise ValueError("Release contract differs from the source contract")
    verify_checksums(dist)
    print(f"Verified {index['releaseVersion']} with {len(index['bundles'])} bundles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
