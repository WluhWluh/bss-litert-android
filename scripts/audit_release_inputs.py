#!/usr/bin/env python3
"""Audit complete-runtime source, packaging inputs, and candidate contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from verify_native_artifacts import expected_native_paths


LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
RELEVANT_PREFIXES = (
    "config/complete-runtime",
    "contracts/",
    "packaging/",
    "patches/complete-runtime/",
    "publication/",
    "scripts/",
)
BINARY_PATCH_MARKERS = (
    b"GIT binary patch",
    b"Binary files ",
    b"literal 0\n",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, int | str]:
    return {"bytes": path.stat().st_size, "sha256": sha256(path)}


def tracked_files(repository: Path, git: str) -> list[str]:
    result = subprocess.run(
        [git, "-C", str(repository), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return sorted(
        entry.decode("utf-8")
        for entry in result.stdout.split(b"\0")
        if entry
    )


def audit_repository(repository: Path, git: str) -> tuple[dict, list[str]]:
    tracked = tracked_files(repository, git)
    errors = []
    forbidden_binary = [
        relative
        for relative in tracked
        if Path(relative).suffix.lower() in (".aar", ".so")
    ]
    if forbidden_binary:
        errors.append(
            f"Repository tracks release binary inputs: {forbidden_binary}"
        )
    patches = [relative for relative in tracked if relative.endswith(".patch")]
    for relative in patches:
        data = (repository / relative).read_bytes()
        marker = next((item for item in BINARY_PATCH_MARKERS if item in data), None)
        if marker:
            errors.append(
                f"Binary patch marker {marker!r} found in {relative}"
            )
    relevant = {
        relative: file_record(repository / relative)
        for relative in tracked
        if relative.startswith(RELEVANT_PREFIXES)
    }
    return {
        "trackedFileCount": len(tracked),
        "releaseInputHashes": relevant,
        "textPatchCount": len(patches),
    }, errors


def audit_source_placeholders(source_tree: Path) -> tuple[dict, list[str]]:
    placeholders = []
    errors = []
    for suffix in ("*.aar", "*.so"):
        for path in sorted(source_tree.rglob(suffix)):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(source_tree).as_posix()
            prefix = path.read_bytes()[: len(LFS_PREFIX)]
            if prefix == LFS_PREFIX:
                placeholders.append(relative)
            else:
                errors.append(
                    f"Source tree contains a materialized binary input: {relative}"
                )
    oclq = [
        path.relative_to(source_tree).as_posix()
        for path in source_tree.rglob("libOCLQ.so")
        if path.is_file()
    ]
    if oclq:
        errors.append(f"Diagnostic libOCLQ.so is present in source inputs: {oclq}")
    return {"lfsBinaryPlaceholders": placeholders}, errors


def expected_component_paths(contract: dict, mode: str) -> set[str]:
    paths = {
        "api/litert-bss-api.aar",
        "LICENSE-LiteRT.txt",
        "THIRD_PARTY_LICENSES.txt",
        "THIRD_PARTY_NOTICES.md",
    }
    paths.update(
        f"native/{relative}"
        for relative in expected_native_paths(contract, mode)
    )
    return paths


def audit_component_dir(
    component_dir: Path,
    component_manifest: dict,
    contract: dict,
    source_lock: dict,
    mode: str,
) -> tuple[dict, list[str]]:
    errors = []
    actual = {
        path.relative_to(component_dir).as_posix(): path
        for path in component_dir.rglob("*")
        if path.is_file()
    }
    expected = expected_component_paths(contract, mode)
    if set(actual) != expected:
        errors.append(
            "Component file drift; "
            f"missing={sorted(expected - actual.keys())}, "
            f"extra={sorted(actual.keys() - expected)}"
        )
    records = {name: file_record(path) for name, path in sorted(actual.items())}
    if component_manifest.get("components") != records:
        errors.append("Component manifest hashes do not match component files.")
    if component_manifest.get("mode") != mode:
        errors.append("Component manifest mode does not match the audit mode.")
    if component_manifest.get("liteRt") != source_lock.get("liteRt"):
        errors.append("Component manifest LiteRT source does not match the lock.")
    if component_manifest.get("patchSeries") != source_lock.get("patchSeries"):
        errors.append("Component manifest patch series does not match the lock.")
    for name, path in actual.items():
        if name.endswith(".so") and path.read_bytes()[:4] != b"\x7fELF":
            errors.append(f"Component native library is not ELF: {name}")
        if Path(name).name == "libOCLQ.so":
            errors.append("Diagnostic libOCLQ.so entered the component directory.")
    return {"files": records}, errors


def archive_entries(path: Path) -> tuple[dict[str, bytes], list[str]]:
    errors = []
    entries = {}
    with zipfile.ZipFile(path) as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            errors.append(f"Archive contains duplicate entries: {duplicates}")
        for name in names:
            entries[name] = archive.read(name)
    return entries, errors


def audit_api_classes(entries: dict[str, bytes], contract: dict) -> list[str]:
    errors = []
    classes = entries.get("classes.jar")
    if classes is None:
        return ["Candidate AAR does not contain classes.jar."]
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(classes)) as archive:
        class_names = set(archive.namelist())
    for prefix in contract["api"]["forbiddenClassPrefixes"]:
        matches = sorted(name for name in class_names if name.startswith(prefix))
        if matches:
            errors.append(f"Forbidden packaged API class: {matches[0]}")
    return errors


def audit_candidate(
    aar: Path,
    component_dir: Path,
    contract: dict,
    mode: str,
) -> tuple[dict, list[str]]:
    entries, errors = archive_entries(aar)
    errors.extend(audit_api_classes(entries, contract))
    nested = sorted(
        name
        for name in entries
        if name.endswith(".aar")
        or (name.endswith(".so") and not name.startswith("jni/"))
    )
    if nested:
        errors.append(f"Candidate contains nested or misplaced binaries: {nested}")
    if any(Path(name).name == "libOCLQ.so" for name in entries):
        errors.append("Candidate contains diagnostic libOCLQ.so.")

    expected_native = set()
    if mode == "complete":
        expected_native = {
            f"jni/{relative}"
            for relative in expected_native_paths(contract, mode)
        }
    actual_native = {
        name
        for name in entries
        if name.startswith("jni/") and name.endswith(".so")
    }
    if actual_native != expected_native:
        errors.append(
            "Candidate native matrix drift; "
            f"missing={sorted(expected_native - actual_native)}, "
            f"extra={sorted(actual_native - expected_native)}"
        )
    for name in sorted(expected_native & actual_native):
        component = component_dir / "native" / name.removeprefix("jni/")
        if not component.is_file() or entries[name] != component.read_bytes():
            errors.append(f"Candidate native bytes differ from component: {name}")
    records = {
        name: {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for name, data in sorted(entries.items())
    }
    return {"path": aar.name, "entries": records}, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-tree", type=Path, required=True)
    parser.add_argument("--component-dir", type=Path, required=True)
    parser.add_argument("--component-manifest", type=Path, required=True)
    parser.add_argument("--candidate-aar", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("available-components", "complete"),
        required=True,
    )
    parser.add_argument("--git", default="git")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    repository = args.repository.resolve()
    source_tree = args.source_tree.resolve()
    component_dir = args.component_dir.resolve()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    source_lock = json.loads(args.source_lock.read_text(encoding="utf-8"))
    component_manifest = json.loads(
        args.component_manifest.read_text(encoding="utf-8")
    )

    repository_report, repository_errors = audit_repository(repository, args.git)
    source_report, source_errors = audit_source_placeholders(source_tree)
    component_report, component_errors = audit_component_dir(
        component_dir,
        component_manifest,
        contract,
        source_lock,
        args.mode,
    )
    candidate_report, candidate_errors = audit_candidate(
        args.candidate_aar.resolve(), component_dir, contract, args.mode
    )
    errors = (
        repository_errors
        + source_errors
        + component_errors
        + candidate_errors
    )
    report = {
        "schemaVersion": 1,
        "mode": args.mode,
        "repository": repository_report,
        "source": source_report,
        "components": component_report,
        "candidate": candidate_report,
        "errors": errors,
    }
    output = args.report.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Verified release inputs: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
