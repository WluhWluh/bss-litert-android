#!/usr/bin/env python3
"""Validate a locally staged Booming SS LiteRT Maven publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_allowlist(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def require_zip_entries(path: Path, required: set[str]) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = {name for name in archive.namelist() if not name.endswith("/")}
    missing = sorted(required - entries)
    if missing:
        raise ValueError(f"{path.name} is missing: {', '.join(missing)}")


def verify_checksums(files: list[Path]) -> None:
    for path in files:
        sidecar = path.with_name(f"{path.name}.sha256")
        if not sidecar.is_file():
            raise FileNotFoundError(f"Missing SHA-256 sidecar: {sidecar.name}")
        checksum = sidecar.read_text(encoding="ascii").strip()
        if checksum != sha256(path):
            raise ValueError(f"Invalid SHA-256 sidecar: {sidecar.name}")


def verify_pom(path: Path, group: str, artifact: str, version: str) -> None:
    root = ET.parse(path).getroot()
    namespace = {"m": "http://maven.apache.org/POM/4.0.0"}

    def text(name: str) -> str | None:
        value = root.find(f"m:{name}", namespace)
        return value.text if value is not None else None

    actual = (text("groupId"), text("artifactId"), text("version"))
    if actual != (group, artifact, version):
        raise ValueError(f"Unexpected POM coordinate: {actual}")
    if text("packaging") != "aar":
        raise ValueError("POM packaging must be aar.")
    pom_text = path.read_text(encoding="utf-8")
    for forbidden in (
        "com.google.ai.edge.litert",
        "com.google.android.play",
        "ai-delivery",
    ):
        if forbidden in pom_text:
            raise ValueError(f"Forbidden POM dependency marker: {forbidden}")


def verify_module(path: Path, group: str, artifact: str, version: str) -> None:
    module = json.loads(path.read_text(encoding="utf-8"))
    if module.get("formatVersion") != "1.1":
        raise ValueError("Unsupported Gradle module metadata format.")
    component = module["component"]
    actual = (component["group"], component["module"], component["version"])
    if actual != (group, artifact, version):
        raise ValueError(f"Unexpected Gradle module coordinate: {actual}")
    expected_aar = f"{artifact}-{version}.aar"
    variants = module.get("variants", [])
    if {variant["name"] for variant in variants} != {
        "releaseApiElements",
        "releaseRuntimeElements",
    }:
        raise ValueError("Gradle module variants are incomplete.")
    for variant in variants:
        files = variant.get("files", [])
        if len(files) != 1 or files[0].get("name") != expected_aar:
            raise ValueError(f"Invalid module files for {variant['name']}.")
    module_text = path.read_text(encoding="utf-8")
    for forbidden in (
        "com.google.ai.edge.litert",
        "com.google.android.play",
        "ai-delivery",
    ):
        if forbidden in module_text:
            raise ValueError(f"Forbidden module dependency marker: {forbidden}")


def verify_native_matrix(aar: Path, contract: dict, api_only: bool) -> None:
    with zipfile.ZipFile(aar) as archive:
        entries = set(archive.namelist())
    actual = {
        name for name in entries if name.startswith("jni/") and name.endswith(".so")
    }
    expected = {
        f"jni/{abi}/{library}"
        for library, abis in contract["nativeLibraries"].items()
        for abi in abis
    }
    if api_only:
        if actual:
            raise ValueError("API-only staging fixture unexpectedly contains JNI.")
    elif actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"Invalid native matrix; missing={missing}, extra={extra}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--source-files", type=Path, required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--require-signatures", action="store_true")
    parser.add_argument("--allow-api-only", action="store_true")
    args = parser.parse_args()

    prefix = f"{args.artifact}-{args.version}"
    version_dir = (
        args.repository.resolve()
        / Path(*args.group.split("."))
        / args.artifact
        / args.version
    )
    expected_names = {
        f"{prefix}.aar",
        f"{prefix}-sources.jar",
        f"{prefix}-javadoc.jar",
        f"{prefix}.pom",
        f"{prefix}.module",
        f"{prefix}-cyclonedx.json",
        f"{prefix}-build-manifest.json",
        f"{prefix}-third-party-licenses.txt",
        f"{prefix}-notices.txt",
    }
    payloads = [version_dir / name for name in sorted(expected_names)]
    missing = [path.name for path in payloads if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing staged Maven files: {', '.join(missing)}")

    verify_checksums(payloads)
    if args.require_signatures:
        unsigned = [
            path.name
            for path in payloads
            if not path.with_name(f"{path.name}.asc").is_file()
        ]
        if unsigned:
            raise FileNotFoundError(f"Missing signatures: {', '.join(unsigned)}")

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    verify_pom(version_dir / f"{prefix}.pom", args.group, args.artifact, args.version)
    verify_module(
        version_dir / f"{prefix}.module",
        args.group,
        args.artifact,
        args.version,
    )
    verify_native_matrix(
        version_dir / f"{prefix}.aar",
        contract,
        args.allow_api_only,
    )

    required_sources = source_allowlist(args.source_files)
    required_sources.add("META-INF/LICENSE-LiteRT.txt")
    require_zip_entries(version_dir / f"{prefix}-sources.jar", required_sources)
    require_zip_entries(
        version_dir / f"{prefix}-javadoc.jar",
        {"element-list", "index.html"},
    )

    sbom = json.loads(
        (version_dir / f"{prefix}-cyclonedx.json").read_text(encoding="utf-8")
    )
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
        raise ValueError("Invalid CycloneDX metadata.")
    print(f"Verified Maven staging repository: {version_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
