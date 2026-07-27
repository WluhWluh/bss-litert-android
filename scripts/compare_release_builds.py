#!/usr/bin/env python3
"""Compare two independent complete-runtime build and Maven trees."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def excluded_signature(relative: str) -> bool:
    return ".asc" in Path(relative).name


def file_tree(root: Path) -> tuple[dict[str, dict[str, int | str]], list[str]]:
    records = {}
    signatures = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Comparison tree contains a symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if excluded_signature(relative):
            signatures.append(relative)
            continue
        records[relative] = {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
    return records, signatures


def compare_trees(first: Path, second: Path) -> dict:
    first_files, first_signatures = file_tree(first)
    second_files, second_signatures = file_tree(second)
    first_names = set(first_files)
    second_names = set(second_files)
    changed = sorted(
        name
        for name in first_names & second_names
        if first_files[name] != second_files[name]
    )
    return {
        "identical": first_files == second_files,
        "missingFromFirst": sorted(second_names - first_names),
        "missingFromSecond": sorted(first_names - second_names),
        "changed": changed,
        "files": first_files,
        "excludedSignatures": {
            "first": first_signatures,
            "second": second_signatures,
        },
    }


def coordinate_dir(
    repository: Path, group: str, artifact: str, version: str
) -> Path:
    return repository.resolve() / Path(*group.split(".")) / artifact / version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-build-dir", type=Path, required=True)
    parser.add_argument("--second-build-dir", type=Path, required=True)
    parser.add_argument("--first-repository", type=Path, required=True)
    parser.add_argument("--second-repository", type=Path, required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    build_comparison = compare_trees(
        args.first_build_dir.resolve(), args.second_build_dir.resolve()
    )
    maven_comparison = compare_trees(
        coordinate_dir(
            args.first_repository, args.group, args.artifact, args.version
        ),
        coordinate_dir(
            args.second_repository, args.group, args.artifact, args.version
        ),
    )
    reproducible = (
        build_comparison["identical"] and maven_comparison["identical"]
    )
    report = {
        "schemaVersion": 1,
        "coordinate": f"{args.group}:{args.artifact}:{args.version}",
        "reproducible": reproducible,
        "build": build_comparison,
        "maven": maven_comparison,
        "signaturePolicy": (
            "Detached OpenPGP signatures and their checksum sidecars are "
            "verified separately and excluded because OpenPGP signatures "
            "contain creation-time entropy."
        ),
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if not reproducible:
        print(f"Release builds differ; see {output}")
        return 1
    print(f"Verified reproducible release trees: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
