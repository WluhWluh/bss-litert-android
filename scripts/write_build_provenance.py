#!/usr/bin/env python3
"""Write deterministic complete-runtime build provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_output(arguments: list[str]) -> str:
    result = subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return "\n".join(
        line.rstrip()
        for line in (result.stdout + result.stderr).splitlines()
        if line.strip()
    )


def git_output(git: str, repository: Path, *arguments: str) -> str:
    return command_output([git, "-C", str(repository), *arguments])


def read_environment(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        if not separator or not key:
            raise ValueError(f"Invalid environment entry: {line}")
        values[key] = value
    return values


def ndk_revision(ndk_dir: Path) -> str:
    properties = ndk_dir / "source.properties"
    for line in properties.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "Pkg.Revision":
            return value.strip()
    raise ValueError(f"NDK revision not found in {properties}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-tree", type=Path, required=True)
    parser.add_argument("--dependency-graph", type=Path, required=True)
    parser.add_argument("--bazel", required=True)
    parser.add_argument("--java", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--git", required=True)
    parser.add_argument("--ndk-dir", type=Path, required=True)
    parser.add_argument("--android-sdk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()

    repository = args.repository.resolve()
    source_tree = args.source_tree.resolve()
    source_lock_path = args.source_lock.resolve()
    contract_path = args.contract.resolve()
    graph = args.dependency_graph.resolve()
    environment_path = args.environment.resolve()
    environment = read_environment(environment_path)
    source_lock = json.loads(source_lock_path.read_text(encoding="utf-8"))

    repository_status = git_output(
        args.git, repository, "status", "--porcelain=v1", "--untracked-files=all"
    ).splitlines()
    if args.require_clean and repository_status:
        raise RuntimeError(
            "Release build repository is not clean: "
            + ", ".join(repository_status)
        )
    source_commit = git_output(args.git, source_tree, "rev-parse", "HEAD")
    if source_commit != source_lock["liteRt"]["commit"]:
        raise ValueError("Checked-out LiteRT commit differs from the source lock.")
    if not graph.is_file() or graph.stat().st_size == 0:
        raise ValueError("Dependency graph is missing or empty.")

    aapt2 = (
        args.android_sdk.resolve()
        / "build-tools"
        / environment["ANDROID_BUILD_TOOLS_VERSION"]
        / "aapt2"
    )
    report = {
        "schemaVersion": 1,
        "repository": {
            "commit": git_output(args.git, repository, "rev-parse", "HEAD"),
            "status": repository_status,
        },
        "liteRt": {
            "repository": source_lock["liteRt"]["repository"],
            "commit": source_commit,
        },
        "configuration": environment,
        "tools": {
            "bazel": command_output([args.bazel, "--version"]),
            "git": command_output([args.git, "--version"]),
            "java": command_output([args.java, "-version"]),
            "python": command_output([args.python, "--version"]),
            "aapt2": command_output([str(aapt2), "version"]),
            "ndk": ndk_revision(args.ndk_dir.resolve()),
        },
        "inputs": {
            "complete-runtime.env": sha256(environment_path),
            "complete-runtime-source-lock.json": sha256(source_lock_path),
            "complete-runtime-contract.json": sha256(contract_path),
            "dependency-graph.txt": sha256(graph),
        },
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
