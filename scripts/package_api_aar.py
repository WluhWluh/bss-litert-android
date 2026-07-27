#!/usr/bin/env python3
"""Package the compiled core LiteRT API as a deterministic pure API AAR."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from deterministic_archive import archive_bytes, write_archive


def read_classes_jar(path: Path) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename.rstrip("/")
            if not name or info.is_dir():
                continue
            if name in entries:
                raise ValueError(f"Duplicate classes JAR entry: {name}")
            entries[name] = archive.read(info)
    class_entries = [name for name in entries if name.endswith(".class")]
    if not class_entries:
        raise ValueError("Compiled classes JAR contains no class files.")
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classes-jar", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    normalized_classes = archive_bytes(read_classes_jar(args.classes_jar))
    write_archive(
        args.output.resolve(),
        {
            "AndroidManifest.xml": args.manifest.read_bytes(),
            "classes.jar": normalized_classes,
        },
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
