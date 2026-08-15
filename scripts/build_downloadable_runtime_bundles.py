#!/usr/bin/env python3
"""Build deterministic downloadable LiteRT components from pinned inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

from deterministic_archive import write_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = REPO_ROOT / "contracts/downloadable-runtime-contract.json"
DEFAULT_API_AAR = (
    REPO_ROOT
    / "dist/downloadable-api/litert-api-2.2.0-bss.1-explicit-loader-base.aar"
)
DEFAULT_API_SOURCE_LOCK = REPO_ROOT / "config/downloadable-api-source-lock.json"
DEFAULT_OUTPUT = REPO_ROOT / "dist/downloadable-runtime"
DEFAULT_CACHE = REPO_ROOT / ".cache/downloadable-runtime"
PACKAGED_RUNTIME_CONTRACT = "META-INF/bss-litert/bounded-gpu-runtime-contract.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_checksums(output_dir: Path) -> None:
    assets = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS"
    )
    (output_dir / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in assets),
        encoding="ascii",
        newline="\n",
    )


def read_archive(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        entries = {info.filename: archive.read(info) for info in infos}
    if len(entries) != len(infos):
        raise ValueError(f"Archive contains duplicate entries: {path}")
    return entries


def require_blob(data: bytes, metadata: dict, label: str) -> None:
    actual_size = len(data)
    actual_sha256 = sha256_bytes(data)
    if actual_size != metadata["byteSize"] or actual_sha256 != metadata["sha256"]:
        raise ValueError(
            f"{label} differs from the frozen contract: "
            f"expected {metadata['byteSize']}/{metadata['sha256']}, "
            f"got {actual_size}/{actual_sha256}"
        )


def source_is_valid(path: Path, metadata: dict) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == metadata["byteSize"]
        and sha256_file(path) == metadata["sha256"]
    )


def materialize_source_aar(
    supplied: Path | None,
    metadata: dict,
    cache_dir: Path,
) -> Path:
    if supplied is not None:
        source = supplied.resolve()
        if not source_is_valid(source, metadata):
            raise ValueError(f"Supplied source AAR does not match the contract: {source}")
        return source

    cache_dir.mkdir(parents=True, exist_ok=True)
    source = cache_dir / metadata["fileName"]
    if source_is_valid(source, metadata):
        return source

    temporary = source.with_suffix(f"{source.suffix}.part")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(
        metadata["url"],
        headers={"User-Agent": "bss-litert-downloadable-runtime-builder/2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            with temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
        if not source_is_valid(temporary, metadata):
            raise ValueError("Downloaded source AAR does not match the frozen identity")
        temporary.replace(source)
    finally:
        temporary.unlink(missing_ok=True)
    return source


def native_file_manifest(metadata: dict, include_role: bool = False) -> dict:
    manifest = {
        "path": metadata["path"],
        "byteSize": metadata["byteSize"],
        "sha256": metadata["sha256"],
        "elf": {
            "class": metadata["elfClass"],
            "machine": metadata["machine"],
            "soname": metadata["soname"],
            "needed": metadata["needed"],
            "loadAlignment": metadata["loadAlignment"],
        },
    }
    if include_role:
        manifest["role"] = metadata["role"]
    if "runtimeLoads" in metadata:
        manifest["runtimeLoads"] = metadata["runtimeLoads"]
    return manifest


def cpu_file_manifest(contract: dict, abi: str, metadata: dict) -> dict:
    del contract, abi
    return native_file_manifest(metadata, include_role=True)


def common_manifest(
    contract: dict,
    component: str,
    abi: str,
    schema_version: int,
) -> dict:
    return {
        "schemaVersion": schema_version,
        "contractSchemaVersion": contract["schemaVersion"],
        "releaseVersion": contract["releaseVersion"],
        "runtimeArtifactVersion": contract["runtimeArtifactVersion"],
        "baseLiteRtVersion": contract["baseLiteRtVersion"],
        "androidMinApi": contract["androidMinApi"],
        "component": component,
        "abi": abi,
        "sourceAar": {
            "fileName": contract["sourceAar"]["fileName"],
            "sha256": contract["sourceAar"]["sha256"],
        },
    }


def build_api_aar(
    base_api_entries: dict[str, bytes],
    contract: dict,
    contract_bytes: bytes,
    source_lock_bytes: bytes,
    output_dir: Path,
) -> Path:
    metadata = contract["apiAar"]
    if any(name.startswith("jni/") for name in base_api_entries):
        raise ValueError("Explicit-loader base API AAR contains native code")
    classes = base_api_entries.get("classes.jar")
    if classes is None:
        raise ValueError("Explicit-loader base API AAR has no classes.jar")
    if len(classes) != metadata["classesJarByteSize"]:
        raise ValueError("Explicit-loader classes.jar size differs from the contract")
    if sha256_bytes(classes) != metadata["classesJarSha256"]:
        raise ValueError("Explicit-loader classes.jar SHA-256 differs from the contract")
    if len(source_lock_bytes) != metadata["sourceLockByteSize"]:
        raise ValueError("Downloadable API source lock size differs from the contract")
    if sha256_bytes(source_lock_bytes) != metadata["sourceLockSha256"]:
        raise ValueError("Downloadable API source lock SHA-256 differs from the contract")

    excluded = {
        PACKAGED_RUNTIME_CONTRACT,
        metadata["embeddedContractPath"],
        metadata["embeddedSourceLockPath"],
    }
    api_entries = {
        name: data for name, data in base_api_entries.items() if name not in excluded
    }
    api_entries[metadata["embeddedContractPath"]] = contract_bytes
    api_entries[metadata["embeddedSourceLockPath"]] = source_lock_bytes
    output = output_dir / metadata["fileName"]
    write_archive(output, api_entries)
    return output


def build_cpu_bundles(
    source_entries: dict[str, bytes],
    contract: dict,
    output_dir: Path,
) -> list[dict]:
    cpu = contract["cpuCore"]
    records = []
    for abi, metadata in sorted(cpu["abis"].items()):
        paths = [file_metadata["path"] for file_metadata in metadata["files"]]
        roles = [file_metadata["role"] for file_metadata in metadata["files"]]
        if paths != cpu["loadOrder"] or roles != ["runtime", "jni"]:
            raise ValueError(f"CPU file/load order differs from the contract: {abi}")

        manifest = common_manifest(
            contract,
            "cpu-core",
            abi,
            cpu["componentManifestSchemaVersion"],
        )
        manifest["capabilities"] = ["cpu"]
        manifest["loadOrder"] = cpu["loadOrder"]
        manifest["files"] = []
        archive_entries: dict[str, bytes] = {}
        for file_metadata in metadata["files"]:
            library = source_entries.get(file_metadata["sourcePath"])
            if library is None:
                raise ValueError(f"Source AAR is missing {file_metadata['sourcePath']}")
            require_blob(library, file_metadata, file_metadata["sourcePath"])
            manifest["files"].append(cpu_file_manifest(contract, abi, file_metadata))
            archive_entries[file_metadata["path"]] = library

        manifest_bytes = json_bytes(manifest)
        archive_entries["manifest.json"] = manifest_bytes
        bundle = output_dir / metadata["bundleFileName"]
        write_archive(bundle, archive_entries)
        records.append(
            {
                "component": "cpu-core",
                "abi": abi,
                "fileName": bundle.name,
                "byteSize": bundle.stat().st_size,
                "sha256": sha256_file(bundle),
                "manifestSha256": sha256_bytes(manifest_bytes),
            }
        )
    return records


def build_gpu_bundle(
    source_entries: dict[str, bytes],
    contract: dict,
    output_dir: Path,
) -> dict:
    metadata = contract["boundedGpu"]
    manifest = common_manifest(
        contract,
        "bounded-gpu",
        metadata["abi"],
        metadata["componentManifestSchemaVersion"],
    )
    manifest["capabilities"] = ["gpu-opencl-bounded-fp32"]
    manifest["requiredCore"] = metadata["requiredCore"]
    manifest["profile"] = metadata["profile"]
    manifest["files"] = []
    archive_entries: dict[str, bytes] = {}
    for file_metadata in metadata["files"]:
        library = source_entries.get(file_metadata["sourcePath"])
        if library is None:
            raise ValueError(f"Source AAR is missing {file_metadata['sourcePath']}")
        require_blob(library, file_metadata, file_metadata["sourcePath"])
        manifest["files"].append(native_file_manifest(file_metadata))
        archive_entries[file_metadata["path"]] = library
    manifest_bytes = json_bytes(manifest)
    archive_entries["manifest.json"] = manifest_bytes
    bundle = output_dir / metadata["bundleFileName"]
    write_archive(bundle, archive_entries)
    return {
        "component": "bounded-gpu",
        "abi": metadata["abi"],
        "fileName": bundle.name,
        "byteSize": bundle.stat().st_size,
        "sha256": sha256_file(bundle),
        "manifestSha256": sha256_bytes(manifest_bytes),
    }


def build_release(
    source_aar: Path,
    base_api_aar: Path,
    contract_path: Path,
    source_lock_path: Path,
    output_dir: Path,
) -> None:
    contract_bytes = contract_path.read_bytes()
    contract = json.loads(contract_bytes)
    source_entries = read_archive(source_aar)
    api_metadata = contract["apiAar"]
    if base_api_aar.stat().st_size != api_metadata["baseByteSize"]:
        raise ValueError("Explicit-loader base API AAR size differs from the contract")
    if sha256_file(base_api_aar) != api_metadata["baseSha256"]:
        raise ValueError("Explicit-loader base API AAR SHA-256 differs from the contract")
    base_api_entries = read_archive(base_api_aar)
    source_lock_bytes = source_lock_path.read_bytes()

    output_dir = output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    api_aar = build_api_aar(
        base_api_entries,
        contract,
        contract_bytes,
        source_lock_bytes,
        output_dir,
    )
    bundles = build_cpu_bundles(source_entries, contract, output_dir)
    bundles.append(build_gpu_bundle(source_entries, contract, output_dir))

    license_mapping = {
        "LICENSE-LiteRT.txt": "LICENSE",
        "THIRD_PARTY_NOTICE-LiteRT.txt": "THIRD_PARTY_NOTICE.txt",
    }
    for destination, source in license_mapping.items():
        data = source_entries.get(source)
        if data is None:
            raise ValueError(f"Source AAR is missing {source}")
        (output_dir / destination).write_bytes(data)
    (output_dir / "downloadable-runtime-contract.json").write_bytes(contract_bytes)
    (output_dir / "downloadable-api-source-lock.json").write_bytes(source_lock_bytes)

    base_url = (
        "https://github.com/WluhWluh/bss-litert-android/releases/download/"
        f"{contract['releaseTag']}"
    )
    index = {
        "schemaVersion": 2,
        "contractSchemaVersion": contract["schemaVersion"],
        "releaseVersion": contract["releaseVersion"],
        "releaseTag": contract["releaseTag"],
        "runtimeArtifactVersion": contract["runtimeArtifactVersion"],
        "sourceAar": contract["sourceAar"],
        "apiAar": {
            "fileName": api_aar.name,
            "byteSize": api_aar.stat().st_size,
            "sha256": sha256_file(api_aar),
            "downloadUrl": f"{base_url}/{api_aar.name}",
        },
        "apiSourceLock": {
            "fileName": "downloadable-api-source-lock.json",
            "byteSize": len(source_lock_bytes),
            "sha256": sha256_bytes(source_lock_bytes),
        },
        "bundles": [
            {**record, "downloadUrl": f"{base_url}/{record['fileName']}"}
            for record in sorted(bundles, key=lambda value: value["fileName"])
        ],
    }
    (output_dir / "downloadable-runtime-index.json").write_bytes(json_bytes(index))
    write_checksums(output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-aar", type=Path)
    parser.add_argument("--api-aar", type=Path, default=DEFAULT_API_AAR)
    parser.add_argument(
        "--api-source-lock",
        type=Path,
        default=DEFAULT_API_SOURCE_LOCK,
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    source = materialize_source_aar(args.source_aar, contract["sourceAar"], args.cache_dir)
    build_release(
        source,
        args.api_aar.resolve(),
        args.contract.resolve(),
        args.api_source_lock.resolve(),
        args.output_dir,
    )
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
