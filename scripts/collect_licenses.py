#!/usr/bin/env python3
"""Collect text license files from Bazel external repositories."""

from __future__ import annotations

import argparse
from pathlib import Path


LICENSE_PREFIXES = ("license", "copying", "notice")
MAX_LICENSE_BYTES = 2 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def is_license(path: Path) -> bool:
    return path.is_file() and path.name.lower().startswith(LICENSE_PREFIXES)


def main() -> int:
    args = parse_args()
    external_dir = args.external_dir.resolve()
    if not external_dir.is_dir():
        raise FileNotFoundError(f"Bazel external directory not found: {external_dir}")

    candidates: list[tuple[str, Path]] = []
    for repository in sorted(external_dir.iterdir(), key=lambda path: path.name.lower()):
        if not repository.is_dir() or repository.name.startswith("@"):
            continue
        for path in sorted(repository.rglob("*"), key=lambda item: item.as_posix().lower()):
            try:
                relative = path.relative_to(repository)
            except ValueError:
                continue
            if len(relative.parts) > 3 or not is_license(path):
                continue
            if path.stat().st_size > MAX_LICENSE_BYTES:
                continue
            candidates.append((repository.name, path))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as output:
        output.write("Third-party licenses collected from the LiteRT Bazel build\n")
        output.write("===========================================================\n")
        for repository, path in candidates:
            relative = path.relative_to(external_dir / repository).as_posix()
            data = path.read_bytes()
            if b"\0" in data:
                continue
            output.write(f"\n--- {repository}/{relative} ---\n\n")
            output.write(data.decode("utf-8", errors="replace").rstrip())
            output.write("\n")

    print(f"Collected {len(candidates)} license files into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
