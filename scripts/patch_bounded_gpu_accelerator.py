#!/usr/bin/env python3
"""Redirect the pinned LiteRT OpenCL loader to the fixed Booming SS shim."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


OFFICIAL_ACCELERATOR_SHA256 = (
    "7c63d606a48e9479499c012f6732623f9e6fc26250c5bdf6724af205d73eb0fb"
)
ORIGINAL_LIBRARY = b"libOpenCL.so"
REPLACEMENT_LIBRARY = b"libBssOcl.so"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data = args.input.read_bytes()
    actual_sha256 = sha256(data)
    if actual_sha256 != OFFICIAL_ACCELERATOR_SHA256:
        raise SystemExit(
            "Official LiteRT accelerator hash mismatch: "
            f"expected {OFFICIAL_ACCELERATOR_SHA256}, got {actual_sha256}"
        )
    if len(REPLACEMENT_LIBRARY) != len(ORIGINAL_LIBRARY):
        raise SystemExit("The bounded loader name must preserve the binary size")
    occurrences = data.count(ORIGINAL_LIBRARY)
    if occurrences != 1:
        raise SystemExit(
            f"Expected one OpenCL loader string, found {occurrences}"
        )

    offset = data.index(ORIGINAL_LIBRARY)
    patched = (
        data[:offset]
        + REPLACEMENT_LIBRARY
        + data[offset + len(ORIGINAL_LIBRARY) :]
    )
    if len(patched) != len(data) or patched.count(REPLACEMENT_LIBRARY) != 1:
        raise SystemExit("Bounded OpenCL loader patch is inconsistent")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    print(f"{offset}:{sha256(patched)}")


if __name__ == "__main__":
    main()
