#!/usr/bin/env python3
"""Remove repository-generated Maven metadata from a staged module."""

from __future__ import annotations

import argparse
from pathlib import Path


METADATA_NAMES = {
    "maven-metadata.xml",
    "maven-metadata.xml.md5",
    "maven-metadata.xml.sha1",
    "maven-metadata.xml.sha256",
    "maven-metadata.xml.sha512",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    module_dir = (
        args.repository.resolve()
        / Path(*args.group.split("."))
        / args.artifact
    )
    version_dir = module_dir / args.version
    if not version_dir.is_dir():
        raise NotADirectoryError(version_dir)
    root_files = {path.name: path for path in module_dir.iterdir() if path.is_file()}
    unexpected = sorted(root_files.keys() - METADATA_NAMES)
    if unexpected:
        raise ValueError(f"Unexpected files in Maven module directory: {unexpected}")
    for path in root_files.values():
        path.unlink()
    print(f"Removed {len(root_files)} generated Maven metadata files from {module_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
