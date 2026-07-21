#!/usr/bin/env python3
"""Write SHA256SUMS for every release asset except the checksum file itself."""

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
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()
    dist_dir = args.dist_dir.resolve()
    output = dist_dir / "SHA256SUMS"
    assets = sorted(
        path for path in dist_dir.iterdir() if path.is_file() and path.name != output.name
    )
    output.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in assets),
        encoding="ascii",
        newline="\n",
    )
    print(output.read_text(encoding="ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
