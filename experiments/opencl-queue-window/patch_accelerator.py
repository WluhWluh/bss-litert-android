#!/usr/bin/env python3

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Redirect LiteRT's OpenCL loader to the queue-window shim."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    old_name = b"libOpenCL.so"
    new_name = b"libOCLQ.so"
    if len(new_name) > len(old_name):
        raise ValueError("The replacement loader name does not fit in-place.")

    data = args.input.read_bytes()
    match_count = data.count(old_name)
    if match_count != 1:
        raise ValueError(
            f"Expected exactly one {old_name!r} loader string, found {match_count}."
        )
    offset = data.index(old_name)
    replacement = new_name + b"\0" * (len(old_name) - len(new_name))
    patched = data[:offset] + replacement + data[offset + len(old_name) :]
    if old_name in patched or patched.count(new_name) != 1:
        raise ValueError("Loader string replacement did not produce the expected image.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    print(offset)


if __name__ == "__main__":
    main()
