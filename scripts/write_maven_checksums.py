#!/usr/bin/env python3
"""Write deterministic SHA-256 sidecars for a staged Maven version."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_dir():
        raise NotADirectoryError(directory)

    sidecar_suffixes = (".asc", ".md5", ".sha1", ".sha256", ".sha512")
    files = [
        path
        for path in sorted(directory.iterdir())
        if path.is_file() and not path.name.endswith(sidecar_suffixes)
    ]
    for path in files:
        sidecar = path.with_name(f"{path.name}.sha256")
        sidecar.write_text(
            f"{sha256(path)}\n",
            encoding="ascii",
            newline="\n",
        )
    print(f"Wrote {len(files)} SHA-256 sidecars in {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
