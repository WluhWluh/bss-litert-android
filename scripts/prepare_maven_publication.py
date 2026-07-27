#!/usr/bin/env python3
"""Prepare deterministic Maven publication attachments for the runtime AAR."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import uuid
import zipfile
from pathlib import Path

from deterministic_archive import write_archive


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hashes(path: Path) -> dict[str, str]:
    data = path.read_bytes()
    return {
        "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(),
        "sha1": hashlib.sha1(data, usedforsecurity=False).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sha512": hashlib.sha512(data).hexdigest(),
    }


def archive_components(aar: Path) -> dict[str, dict[str, int | str]]:
    components: dict[str, dict[str, int | str]] = {}
    with zipfile.ZipFile(aar) as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError("AAR contains duplicate entries.")
        for name in sorted(names):
            if name != "classes.jar" and not (
                name.startswith("jni/") and name.endswith(".so")
            ):
                continue
            data = archive.read(name)
            components[name] = {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    if "classes.jar" not in components:
        raise ValueError("AAR does not contain classes.jar.")
    return components


def publication_build_manifest(
    source: dict,
    contract: dict,
    version: str,
    aar: Path,
    allow_api_only: bool,
) -> dict:
    components = archive_components(aar)
    native_components = {
        name for name in components if name.startswith("jni/")
    }
    if allow_api_only:
        if native_components:
            raise ValueError("API-only publication fixture contains JNI libraries.")
    else:
        recorded = {
            name: value
            for name, value in source.get("components", {}).items()
            if name == "classes.jar" or name.startswith("jni/")
        }
        if recorded != components:
            raise ValueError(
                "Build manifest components do not match the publication AAR."
            )
    return {
        "schemaVersion": 1,
        "artifact": {
            "group": contract["artifact"]["group"],
            "name": contract["artifact"]["name"],
            "version": version,
            "minSdk": contract["artifact"]["minSdk"],
            "jvmTarget": contract["artifact"]["jvmTarget"],
        },
        "liteRt": source["liteRt"],
        "patchSeries": source["patchSeries"],
        "components": components,
        "publicationFixture": "api-only" if allow_api_only else "complete",
    }


def read_source_allowlist(path: Path) -> list[str]:
    entries = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not entries or len(entries) != len(set(entries)):
        raise ValueError("API source allowlist must be non-empty and unique.")
    return entries


def api_docs(contract: dict) -> bytes:
    rows = []
    members = dict(contract["api"]["requiredMembers"])
    for class_name, extensions in contract["api"][
        "bssExtensionMembers"
    ].items():
        members.setdefault(class_name, []).extend(extensions)
    for class_name, class_members in sorted(members.items()):
        items = "".join(
            f"<li><code>{html.escape(member)}</code></li>"
            for member in class_members
        )
        rows.append(
            f"<section><h2>{html.escape(class_name)}</h2><ul>{items}</ul></section>"
        )
    body = "".join(rows)
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Booming SS LiteRT Android API</title>
</head>
<body>
<main>
<h1>Booming SS LiteRT Android API</h1>
{body}
</main>
</body>
</html>
"""
    return document.encode("utf-8")


def gradle_module_metadata(
    group: str,
    artifact: str,
    version: str,
    aar: Path,
) -> dict:
    artifact_hashes = hashes(aar)
    file_entry = {
        "name": aar.name,
        "url": aar.name,
        "size": aar.stat().st_size,
        **artifact_hashes,
    }
    common_attributes = {
        "org.gradle.category": "library",
        "org.gradle.dependency.bundling": "external",
        "org.gradle.libraryelements": "aar",
        "org.gradle.status": "release",
    }
    variants = []
    for name, usage in (
        ("releaseApiElements", "java-api"),
        ("releaseRuntimeElements", "java-runtime"),
    ):
        variants.append(
            {
                "name": name,
                "attributes": {
                    **common_attributes,
                    "org.gradle.usage": usage,
                },
                "files": [file_entry],
            }
        )
    return {
        "formatVersion": "1.1",
        "component": {
            "group": group,
            "module": artifact,
            "version": version,
            "attributes": {"org.gradle.status": "release"},
        },
        "createdBy": {"gradle": {"version": "8.9"}},
        "variants": variants,
    }


def cyclonedx_sbom(
    group: str,
    artifact: str,
    version: str,
    aar: Path,
    build_manifest: dict,
) -> dict:
    digest = sha256(aar)
    bom_ref = f"pkg:maven/{group}/{artifact}@{version}?type=aar"
    properties = [
        {"name": "bss.litert.component.count", "value": str(len(build_manifest["components"]))},
        {
            "name": "bss.litert.upstream.commit",
            "value": build_manifest["liteRt"]["commit"],
        },
    ]
    components = []
    for path, component in sorted(build_manifest["components"].items()):
        components.append(
            {
                "type": "file",
                "bom-ref": f"urn:bss-litert:component:{path}",
                "name": path,
                "hashes": [
                    {"alg": "SHA-256", "content": component["sha256"]}
                ],
                "properties": [
                    {
                        "name": "bss.litert.component.bytes",
                        "value": str(component["bytes"]),
                    }
                ],
            }
        )
    return {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, bom_ref + digest)}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "library",
                "bom-ref": bom_ref,
                "group": group,
                "name": artifact,
                "version": version,
                "purl": bom_ref,
                "hashes": [{"alg": "SHA-256", "content": digest}],
                "licenses": [{"license": {"id": "Apache-2.0"}}],
                "properties": properties,
            }
        },
        "components": components,
    }


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aar", type=Path, required=True)
    parser.add_argument("--api-source-root", type=Path, required=True)
    parser.add_argument("--source-files", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--license", type=Path, required=True)
    parser.add_argument("--third-party-licenses", type=Path, required=True)
    parser.add_argument("--notices", type=Path, required=True)
    parser.add_argument("--artifact-version", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-api-only", action="store_true")
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    source_build_manifest = json.loads(
        args.build_manifest.read_text(encoding="utf-8")
    )
    artifact = contract["artifact"]
    group = artifact["group"]
    name = artifact["name"]
    version = args.artifact_version
    prefix = f"{name}-{version}"
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    canonical_aar = output / f"{prefix}.aar"
    shutil.copyfile(args.aar, canonical_aar)
    build_manifest = publication_build_manifest(
        source_build_manifest,
        contract,
        version,
        canonical_aar,
        args.allow_api_only,
    )

    source_entries = {
        relative: (args.api_source_root / relative).read_bytes()
        for relative in read_source_allowlist(args.source_files)
    }
    source_entries["META-INF/LICENSE-LiteRT.txt"] = args.license.read_bytes()
    write_archive(output / f"{prefix}-sources.jar", source_entries)
    write_archive(
        output / f"{prefix}-javadoc.jar",
        {
            "element-list": b"com.google.ai.edge.litert\n",
            "index.html": api_docs(contract),
        },
    )

    write_json(output / f"{prefix}-build-manifest.json", build_manifest)
    shutil.copyfile(
        args.third_party_licenses,
        output / f"{prefix}-third-party-licenses.txt",
    )
    shutil.copyfile(args.notices, output / f"{prefix}-notices.txt")
    write_json(
        output / f"{prefix}-cyclonedx.json",
        cyclonedx_sbom(group, name, version, canonical_aar, build_manifest),
    )
    write_json(
        output / f"{prefix}.module",
        gradle_module_metadata(group, name, version, canonical_aar),
    )

    manifest = {
        "schemaVersion": 1,
        "coordinate": f"{group}:{name}:{version}",
        "files": {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(output.iterdir())
            if path.is_file()
        },
    }
    write_json(output / "publication-inputs.json", manifest)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
