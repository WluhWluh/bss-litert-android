#!/usr/bin/env python3
"""Redirect LiteRT 2.1.5's unused Kotlin GPU option to kernel batching."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


OFFICIAL_RUNTIME_SHA256 = (
    "366e3e040b00692158f9f8f9105870672c93348a3d8e9024120b40045a074b0b"
)

# LrtSetGpuAcceleratorRuntimeOptionsNumStepsOfCommandBufferPreparations:
#   optional<int>.engaged = true at offset 0x98
#   optional<int>.value = argument at offset 0x94
OLD_SETTER = bytes.fromhex(
    "e80300aa"  # mov x8, x0
    "20008052"  # mov w0, #1
    "880000b4"  # cbz x8, return
    "00610239"  # strb w0, [x8, #0x98]
    "e0031f2a"  # mov w0, wzr
    "019500b9"  # str w1, [x8, #0x94]
    "c0035fd6"  # ret
)

# The official binary's kernel_batch_size serializer reads the value from
# offset 0x10c and its engaged flag from offset 0x110.
NEW_SETTER = bytes.fromhex(
    "e80300aa"
    "20008052"
    "880000b4"
    "00410439"  # strb w0, [x8, #0x110]
    "e0031f2a"
    "010d01b9"  # str w1, [x8, #0x10c]
    "c0035fd6"
)

REWRITTEN_INSTRUCTION_BYTES = 8


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    data = args.input.read_bytes()
    actual_sha256 = sha256(data)
    if actual_sha256 != OFFICIAL_RUNTIME_SHA256:
        raise SystemExit(
            "Official LiteRT runtime hash mismatch: "
            f"expected {OFFICIAL_RUNTIME_SHA256}, got {actual_sha256}"
        )

    occurrences = data.count(OLD_SETTER)
    if occurrences != 1:
        raise SystemExit(
            f"Expected one Kotlin GPU option setter, found {occurrences}"
        )
    offset = data.index(OLD_SETTER)
    patched = data[:offset] + NEW_SETTER + data[offset + len(OLD_SETTER) :]
    if len(patched) != len(data):
        raise SystemExit("Patched runtime size changed unexpectedly")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    changed_bytes = sum(old != new for old, new in zip(data, patched))
    print(
        f"{offset}:{sha256(patched)}:{len(OLD_SETTER)}:"
        f"{REWRITTEN_INSTRUCTION_BYTES}:{changed_bytes}"
    )


if __name__ == "__main__":
    main()
