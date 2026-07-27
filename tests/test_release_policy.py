from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from audit_release_inputs import (  # noqa: E402
    LFS_PREFIX,
    audit_repository,
    audit_source_placeholders,
)
from assemble_maven_bundle import main as assemble_bundle_main  # noqa: E402
from compare_release_builds import compare_trees  # noqa: E402
from verify_native_artifacts import (  # noqa: E402
    ElfInspection,
    parse_android_api,
    parse_defined_symbols,
    parse_needed,
    validate_inspection,
)


class ReleasePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(
            (REPO_ROOT / "contracts/complete-runtime-contract.json").read_text(
                encoding="utf-8"
            )
        )

    def test_parses_structured_elf_tool_output(self) -> None:
        document = {
            "Notes": [
                {
                    "NoteSection": {
                        "Name": ".note.android.ident",
                        "Note": {
                            "Description data": {
                                "Bytes": [23, 0, 0, 0, 114, 50, 53, 98]
                            }
                        },
                    }
                }
            ]
        }
        self.assertEqual(parse_android_api(document), 23)
        self.assertEqual(
            parse_needed("NeededLibraries [\nlibm.so\nlibc.so\n]\n"),
            ["libc.so", "libm.so"],
        )
        self.assertEqual(
            parse_defined_symbols(
                "SymbolB@@VERS_1.0 T 2 1\nSymbolA T 1 1\nSymbolA T 1 1\n"
            ),
            ["SymbolA", "SymbolB"],
        )

    def test_validates_known_x86_runtime_contract(self) -> None:
        inspection = ElfInspection(
            path="x86/libLiteRt.so",
            bytes=1,
            sha256="a" * 64,
            elf_class="32-bit",
            machine="EM_386",
            android_api=23,
            soname="LiteRt",
            needed=["libc.so", "libdl.so", "liblog.so", "libm.so"],
            defined_symbols=["LiteRtCreateModelFromBuffer"],
        )
        self.assertEqual(
            validate_inspection(
                inspection,
                "x86",
                "libLiteRt.so",
                self.contract,
                REPO_ROOT,
            ),
            [],
        )

    def test_rejects_native_dependency_drift(self) -> None:
        inspection = ElfInspection(
            path="x86/libLiteRt.so",
            bytes=1,
            sha256="a" * 64,
            elf_class="32-bit",
            machine="EM_386",
            android_api=23,
            soname="LiteRt",
            needed=["libc.so", "libvendor.so"],
            defined_symbols=["LiteRtCreateModelFromBuffer"],
        )
        errors = validate_inspection(
            inspection,
            "x86",
            "libLiteRt.so",
            self.contract,
            REPO_ROOT,
        )
        self.assertTrue(any("DT_NEEDED" in error for error in errors))

    def test_source_scan_allows_lfs_pointers_and_rejects_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            pointer = source / "prebuilt" / "runtime.so"
            pointer.parent.mkdir()
            pointer.write_bytes(
                LFS_PREFIX + b"oid sha256:" + b"a" * 64 + b"\nsize 1\n"
            )
            report, errors = audit_source_placeholders(source)
            self.assertEqual(errors, [])
            self.assertEqual(
                report["lfsBinaryPlaceholders"], ["prebuilt/runtime.so"]
            )

            (source / "prebuilt" / "official.aar").write_bytes(b"PK\x03\x04")
            _, errors = audit_source_placeholders(source)
            self.assertTrue(any("materialized binary" in error for error in errors))

    def test_repository_scan_rejects_tracked_binaries_and_binary_patch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            subprocess.run(
                ["git", "init", str(repository)],
                check=True,
                capture_output=True,
            )
            (repository / "runtime.so").write_bytes(b"\x7fELF")
            patch = repository / "change.patch"
            patch.write_bytes(b"GIT binary patch\nliteral 0\n")
            subprocess.run(
                ["git", "-C", str(repository), "add", "runtime.so", "change.patch"],
                check=True,
                capture_output=True,
            )
            _, errors = audit_repository(repository, "git")
            self.assertTrue(any("binary inputs" in error for error in errors))
            self.assertTrue(any("Binary patch marker" in error for error in errors))

    def test_comparison_excludes_signatures_but_detects_payload_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            (first / "runtime.aar").write_bytes(b"same")
            (second / "runtime.aar").write_bytes(b"same")
            (second / "runtime.aar.asc").write_bytes(b"signature")
            comparison = compare_trees(first, second)
            self.assertTrue(comparison["identical"])
            self.assertEqual(
                comparison["excludedSignatures"]["second"],
                ["runtime.aar.asc"],
            )

            (second / "runtime.aar").write_bytes(b"changed")
            comparison = compare_trees(first, second)
            self.assertFalse(comparison["identical"])
            self.assertEqual(comparison["changed"], ["runtime.aar"])

    def test_maven_bundle_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version_dir = root / "repo" / "example" / "runtime" / "test"
            version_dir.mkdir(parents=True)
            (version_dir / "runtime-test.aar").write_bytes(b"aar")
            (version_dir / "runtime-test.aar.asc").write_bytes(b"signature")

            outputs = []
            original_argv = sys.argv
            try:
                for index in range(2):
                    output = root / f"bundle-{index}.zip"
                    sys.argv = [
                        "assemble_maven_bundle.py",
                        "--repository",
                        str(root / "repo"),
                        "--group",
                        "example",
                        "--artifact",
                        "runtime",
                        "--version",
                        "test",
                        "--output",
                        str(output),
                        "--manifest-output",
                        str(root / f"manifest-{index}.json"),
                        "--require-signatures",
                    ]
                    self.assertEqual(assemble_bundle_main(), 0)
                    outputs.append(output)
            finally:
                sys.argv = original_argv
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())


if __name__ == "__main__":
    unittest.main()
