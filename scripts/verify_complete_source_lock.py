#!/usr/bin/env python3
"""Validate the complete-runtime source lock and optional GPU readiness."""

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
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path("config/complete-runtime-source-lock.json"),
    )
    parser.add_argument(
        "--patch-dir",
        type=Path,
        default=Path("patches/complete-runtime"),
    )
    parser.add_argument("--require-gpu-source", action="store_true")
    args = parser.parse_args()

    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    if lock.get("schemaVersion") != 1:
        raise ValueError("Unsupported complete-runtime source lock schema.")

    patch_dir = args.patch_dir.resolve()
    series = [
        line.strip()
        for line in (patch_dir / "series").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    locked_series = [entry["file"] for entry in lock["patchSeries"]]
    if series != locked_series:
        raise ValueError("Patch series order does not match the source lock.")
    for entry in lock["patchSeries"]:
        patch = patch_dir / entry["file"]
        if sha256(patch) != entry["sha256"]:
            raise ValueError(f"Patch SHA-256 mismatch: {patch}")

    if args.require_gpu_source:
        ml_drift = lock["mlDrift"]
        if (
            ml_drift["sourceStatus"] != "publicly-fetchable"
            or not ml_drift["urls"]
            or not ml_drift["sha256"]
        ):
            raise RuntimeError(
                "Complete GPU build is blocked: ML Drift source is not "
                "publicly fetchable and checksummed."
            )
    print(f"Verified complete-runtime source lock: {args.lock}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
