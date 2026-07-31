#!/usr/bin/env python3
"""Apply a locked patch series to its exact LiteRT base."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
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
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def run_git(source: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
    )


def require_git(source: Path, *args: str) -> str:
    result = run_git(source, *args)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_lock(path: Path) -> dict:
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("schemaVersion") != 1:
        raise ValueError("Unsupported LiteRT source lock schema.")
    return lock


def resolve_patches(lock: dict, patch_dir: Path) -> list[Path]:
    root = patch_dir.resolve()
    series_file = root / "series"
    series = [
        line.strip()
        for line in series_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    locked = [entry["file"] for entry in lock["patchSeries"]]
    if series != locked:
        raise ValueError("Patch series order does not match the source lock.")

    patches: list[Path] = []
    for entry in lock["patchSeries"]:
        patch = (root / entry["file"]).resolve()
        if patch.parent != root:
            raise ValueError(f"Patch escapes the patch directory: {patch}")
        if not patch.is_file():
            raise FileNotFoundError(f"Patch not found: {patch}")
        actual = sha256(patch)
        if actual != entry["sha256"]:
            raise ValueError(
                f"Patch SHA-256 mismatch for {patch.name}: "
                f"expected {entry['sha256']}, got {actual}"
            )
        patches.append(patch)
    return patches


def reject_fuzzy_application(result: subprocess.CompletedProcess[str]) -> None:
    diagnostics = f"{result.stdout}\n{result.stderr}".lower()
    if "offset" in diagnostics or "fuzz" in diagnostics:
        raise RuntimeError(
            "Patch application reported an offset or fuzz:\n"
            f"{result.stdout}{result.stderr}"
        )


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    lock = read_lock(args.lock.resolve())
    patches = resolve_patches(lock, args.patch_dir)

    if not (source / ".git").exists():
        raise ValueError(f"LiteRT source is not a Git worktree: {source}")
    expected_commit = lock["liteRt"]["commit"]
    actual_commit = require_git(source, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise ValueError(
            f"Expected LiteRT commit {expected_commit}, got {actual_commit}."
        )
    status = require_git(source, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise ValueError("LiteRT tracked worktree must be clean before patching.")

    patch_args = [str(path) for path in patches]
    check = run_git(
        source,
        "apply",
        "--check",
        "--verbose",
        "--whitespace=error-all",
        *patch_args,
    )
    if check.returncode != 0:
        detail = check.stderr.strip() or check.stdout.strip()
        raise RuntimeError(f"Patch preflight failed: {detail}")
    reject_fuzzy_application(check)

    if args.verify_only:
        print(f"Verified {len(patches)} patches against {actual_commit}.")
        return 0

    apply_result = run_git(
        source,
        "apply",
        "--index",
        "--verbose",
        "--whitespace=error-all",
        *patch_args,
    )
    if apply_result.returncode != 0:
        detail = apply_result.stderr.strip() or apply_result.stdout.strip()
        raise RuntimeError(f"Patch application failed: {detail}")
    reject_fuzzy_application(apply_result)
    print(f"Applied {len(patches)} patches to {actual_commit}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
