#!/usr/bin/env python3
"""Assemble a deterministic Maven Central upload bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from deterministic_archive import write_archive


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--require-signatures", action="store_true")
    args = parser.parse_args()

    coordinate = Path(*args.group.split(".")) / args.artifact / args.version
    version_dir = args.repository.resolve() / coordinate
    if not version_dir.is_dir():
        raise NotADirectoryError(version_dir)
    entries = {}
    for path in sorted(version_dir.iterdir()):
        if path.is_symlink():
            raise ValueError(f"Maven payload must not contain symlinks: {path}")
        if path.is_file():
            entries[(coordinate / path.name).as_posix()] = path.read_bytes()
    if not entries:
        raise ValueError("Maven version directory is empty.")
    if args.require_signatures:
        unsigned = [
            name
            for name in entries
            if not name.endswith((".asc", ".md5", ".sha1", ".sha256", ".sha512"))
            and f"{name}.asc" not in entries
        ]
        if unsigned:
            raise ValueError(f"Unsigned Maven payloads: {unsigned}")

    output = args.output.resolve()
    write_archive(output, entries)
    manifest = {
        "schemaVersion": 1,
        "coordinate": f"{args.group}:{args.artifact}:{args.version}",
        "bundle": output.name,
        "files": {
            name: {"bytes": len(data), "sha256": sha256(data)}
            for name, data in sorted(entries.items())
        },
    }
    manifest_output = args.manifest_output.resolve()
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
