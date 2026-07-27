#!/usr/bin/env python3
"""Create a deterministic local-Maven bundle for the bounded GPU AAR."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from deterministic_archive import write_archive  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aar", type=Path, required=True)
    parser.add_argument("--pom-template", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository-output", type=Path, required=True)
    parser.add_argument("--bundle-output", type=Path, required=True)
    args = parser.parse_args()

    artifact_dir = (
        args.repository_output
        / "io/github/wluhwluh/bss/litert-android"
        / args.version
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    aar_name = f"litert-android-{args.version}.aar"
    pom_name = f"litert-android-{args.version}.pom"
    aar_output = artifact_dir / aar_name
    pom_output = artifact_dir / pom_name
    aar_output.write_bytes(args.aar.read_bytes())
    pom_output.write_text(
        args.pom_template.read_text(encoding="utf-8").replace(
            "@ARTIFACT_VERSION@", args.version
        ),
        encoding="utf-8",
        newline="\n",
    )

    entries = {
        path.relative_to(args.repository_output).as_posix(): path.read_bytes()
        for path in artifact_dir.iterdir()
        if path.is_file()
    }
    write_archive(args.bundle_output, entries)


if __name__ == "__main__":
    main()
