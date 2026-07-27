#!/usr/bin/env python3
"""Record hashes for a complete-runtime component build."""

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component-dir", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--artifact-version", required=True)
    parser.add_argument(
        "--mode",
        choices=("available-components", "complete"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    component_dir = args.component_dir.resolve()
    output = args.output.resolve()
    files = {
        path.relative_to(component_dir).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(component_dir.rglob("*"))
        if path.is_file() and path.resolve() != output
    }
    source_lock = json.loads(args.source_lock.read_text(encoding="utf-8"))
    manifest = {
        "schemaVersion": 1,
        "artifactVersion": args.artifact_version,
        "mode": args.mode,
        "liteRt": source_lock["liteRt"],
        "patchSeries": source_lock["patchSeries"],
        "components": files,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
