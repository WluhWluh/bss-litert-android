#!/usr/bin/env python3
"""Validate a locally staged Booming SS LiteRT Maven publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_hashes(path: Path) -> dict[str, str]:
    data = path.read_bytes()
    return {
        "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(),
        "sha1": hashlib.sha1(data, usedforsecurity=False).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sha512": hashlib.sha512(data).hexdigest(),
    }


def source_allowlist(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def require_zip_entries(path: Path, required: set[str], exact: bool = False) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = {name for name in archive.namelist() if not name.endswith("/")}
    missing = sorted(required - entries)
    if missing:
        raise ValueError(f"{path.name} is missing: {', '.join(missing)}")
    if exact and entries != required:
        raise ValueError(
            f"{path.name} has unexpected entries: {sorted(entries - required)}"
        )


def verify_checksums(files: list[Path]) -> None:
    for path in files:
        sidecar = path.with_name(f"{path.name}.sha256")
        if not sidecar.is_file():
            raise FileNotFoundError(f"Missing SHA-256 sidecar: {sidecar.name}")
        checksum = sidecar.read_text(encoding="ascii").strip()
        if checksum != sha256(path):
            raise ValueError(f"Invalid SHA-256 sidecar: {sidecar.name}")


def verify_signatures(
    files: list[Path],
    gpg: str,
    gpg_homedir: Path | None,
) -> None:
    for path in files:
        signature = path.with_name(f"{path.name}.asc")
        if not signature.is_file():
            raise FileNotFoundError(f"Missing signature: {signature.name}")
        command = [gpg, "--batch", "--no-auto-key-retrieve"]
        if gpg_homedir:
            command.extend(("--homedir", str(gpg_homedir.resolve())))
        command.extend(("--verify", str(signature), str(path)))
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError(
                f"OpenPGP verification failed for {path.name}: "
                f"{result.stderr.strip()}"
            )


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
    required_metadata = ("name", "description", "url", "licenses", "developers", "scm")
    missing_metadata = [name for name in required_metadata if root.find(f"m:{name}", namespace) is None]
    if missing_metadata:
        raise ValueError(f"POM metadata is incomplete: {missing_metadata}")
    dependencies = root.find("m:dependencies", namespace)
    if dependencies is not None and list(dependencies):
        raise ValueError("Complete runtime POM must not declare dependencies.")
    pom_text = path.read_text(encoding="utf-8")
    for forbidden in (
        "com.google.ai.edge.litert",
        "com.google.android.play",
        "ai-delivery",
    ):
        if forbidden in pom_text:
            raise ValueError(f"Forbidden POM dependency marker: {forbidden}")


def verify_module(
    path: Path,
    group: str,
    artifact: str,
    version: str,
    aar: Path,
) -> None:
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
        expected_file = {
            "name": expected_aar,
            "url": expected_aar,
            "size": aar.stat().st_size,
            **file_hashes(aar),
        }
        if files[0] != expected_file:
            raise ValueError(f"Invalid module hashes for {variant['name']}.")
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


def archive_component_records(aar: Path) -> dict[str, dict[str, int | str]]:
    records = {}
    with zipfile.ZipFile(aar) as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError("Published AAR contains duplicate entries.")
        for name in sorted(names):
            if name != "classes.jar" and not (
                name.startswith("jni/") and name.endswith(".so")
            ):
                continue
            data = archive.read(name)
            records[name] = {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    return records


def verify_build_manifest(
    path: Path,
    aar: Path,
    contract: dict,
    group: str,
    artifact: str,
    version: str,
    source_lock: dict,
    api_only: bool,
) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected_artifact = {
        "group": group,
        "name": artifact,
        "version": version,
        "minSdk": contract["artifact"]["minSdk"],
        "jvmTarget": contract["artifact"]["jvmTarget"],
    }
    if manifest.get("schemaVersion") != 1:
        raise ValueError("Unsupported build manifest schema.")
    if manifest.get("artifact") != expected_artifact:
        raise ValueError("Build manifest artifact contract is invalid.")
    expected_fixture = "api-only" if api_only else "complete"
    if manifest.get("publicationFixture") != expected_fixture:
        raise ValueError("Build manifest publication fixture mode is invalid.")
    if manifest.get("liteRt") != source_lock.get("liteRt"):
        raise ValueError("Build manifest LiteRT source differs from source lock.")
    if manifest.get("patchSeries") != source_lock.get("patchSeries"):
        raise ValueError("Build manifest patches differ from source lock.")
    if manifest.get("components") != archive_component_records(aar):
        raise ValueError("Build manifest components differ from published AAR.")
    return manifest


def verify_sbom(path: Path, aar: Path, manifest: dict) -> None:
    sbom = json.loads(path.read_text(encoding="utf-8"))
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
        raise ValueError("Invalid CycloneDX metadata.")
    component = sbom.get("metadata", {}).get("component", {})
    hashes = component.get("hashes", [])
    if {entry.get("alg"): entry.get("content") for entry in hashes}.get("SHA-256") != sha256(aar):
        raise ValueError("CycloneDX AAR hash is invalid.")
    actual_components = {
        entry.get("name"): {
            item.get("alg"): item.get("content")
            for item in entry.get("hashes", [])
        }.get("SHA-256")
        for entry in sbom.get("components", [])
    }
    expected_components = {
        name: record["sha256"]
        for name, record in manifest["components"].items()
    }
    if actual_components != expected_components:
        raise ValueError("CycloneDX component hashes differ from build manifest.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--source-files", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--require-signatures", action="store_true")
    parser.add_argument("--allow-api-only", action="store_true")
    parser.add_argument("--gpg", default="gpg")
    parser.add_argument("--gpg-homedir", type=Path)
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
        verify_signatures(payloads, args.gpg, args.gpg_homedir)

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    verify_pom(version_dir / f"{prefix}.pom", args.group, args.artifact, args.version)
    aar = version_dir / f"{prefix}.aar"
    verify_module(
        version_dir / f"{prefix}.module",
        args.group,
        args.artifact,
        args.version,
        aar,
    )
    verify_native_matrix(
        aar,
        contract,
        args.allow_api_only,
    )

    source_lock = json.loads(args.source_lock.read_text(encoding="utf-8"))
    manifest = verify_build_manifest(
        version_dir / f"{prefix}-build-manifest.json",
        aar,
        contract,
        args.group,
        args.artifact,
        args.version,
        source_lock,
        args.allow_api_only,
    )

    required_sources = source_allowlist(args.source_files)
    required_sources.add("META-INF/LICENSE-LiteRT.txt")
    require_zip_entries(
        version_dir / f"{prefix}-sources.jar",
        required_sources,
        exact=True,
    )
    require_zip_entries(
        version_dir / f"{prefix}-javadoc.jar",
        {"element-list", "index.html"},
        exact=True,
    )

    verify_sbom(version_dir / f"{prefix}-cyclonedx.json", aar, manifest)
    attachments = {
        "third-party-licenses.txt": "License",
        "notices.txt": "LiteRT",
    }
    for suffix, marker in attachments.items():
        attachment = version_dir / f"{prefix}-{suffix}"
        text = attachment.read_text(encoding="utf-8")
        if len(text) < 100 or marker not in text:
            raise ValueError(f"Invalid publication attachment: {attachment.name}")
    print(f"Verified Maven staging repository: {version_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
