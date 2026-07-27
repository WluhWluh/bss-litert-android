"""Helpers for deterministic ZIP, JAR, and AAR archives."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping
from pathlib import PurePosixPath


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def validate_entry_name(name: str) -> str:
    normalized = PurePosixPath(name).as_posix()
    if (
        not normalized
        or normalized.startswith("/")
        or normalized == "."
        or ".." in PurePosixPath(normalized).parts
        or "\\" in name
    ):
        raise ValueError(f"Unsafe archive entry: {name!r}")
    return normalized


def write_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    normalized = validate_entry_name(name)
    info = zipfile.ZipInfo(normalized, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(
        info,
        data,
        compress_type=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    )


def archive_bytes(entries: Mapping[str, bytes]) -> bytes:
    normalized: dict[str, bytes] = {}
    for name, data in entries.items():
        safe_name = validate_entry_name(name)
        if safe_name in normalized:
            raise ValueError(f"Duplicate archive entry: {safe_name}")
        normalized[safe_name] = data

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name in sorted(normalized):
            write_entry(archive, name, normalized[name])
    return output.getvalue()


def write_archive(path, entries: Mapping[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(archive_bytes(entries))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
