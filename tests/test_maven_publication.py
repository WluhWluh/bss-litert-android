from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from deterministic_archive import write_archive  # noqa: E402
from prepare_maven_publication import (  # noqa: E402
    publication_build_manifest,
    cyclonedx_sbom,
    gradle_module_metadata,
    read_source_allowlist,
)
from verify_maven_staging import verify_checksums  # noqa: E402
from verify_maven_staging import (  # noqa: E402
    verify_build_manifest,
    verify_sbom,
)
from write_maven_checksums import main as write_checksums_main  # noqa: E402


class MavenPublicationTest(unittest.TestCase):
    def test_api_only_manifest_describes_only_packaged_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            aar = Path(directory) / "api.aar"
            write_archive(
                aar,
                {"AndroidManifest.xml": b"manifest", "classes.jar": b"classes"},
            )
            contract = {
                "artifact": {
                    "group": "example",
                    "name": "runtime",
                    "minSdk": 23,
                    "jvmTarget": 17,
                }
            }
            source = {
                "liteRt": {"commit": "a" * 40},
                "patchSeries": [],
                "components": {
                    "native/x86/libLiteRt.so": {
                        "bytes": 6,
                        "sha256": "b" * 64,
                    }
                },
            }
            manifest = publication_build_manifest(
                source, contract, "test", aar, allow_api_only=True
            )
            self.assertEqual(set(manifest["components"]), {"classes.jar"})
            self.assertEqual(manifest["publicationFixture"], "api-only")

    def test_staged_manifest_and_sbom_match_api_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aar = root / "litert-android-test.aar"
            write_archive(
                aar,
                {"AndroidManifest.xml": b"manifest", "classes.jar": b"classes"},
            )
            contract = json.loads(
                (REPO_ROOT / "contracts/complete-runtime-contract.json").read_text(
                    encoding="utf-8"
                )
            )
            source = {
                "liteRt": {
                    "repository": "https://example.invalid/LiteRT.git",
                    "commit": "a" * 40,
                },
                "patchSeries": [],
                "components": {},
            }
            manifest = publication_build_manifest(
                source, contract, "test", aar, allow_api_only=True
            )
            manifest_path = root / "build-manifest.json"
            manifest_path.write_text(
                json.dumps(manifest), encoding="utf-8", newline="\n"
            )
            verified = verify_build_manifest(
                manifest_path,
                aar,
                contract,
                contract["artifact"]["group"],
                contract["artifact"]["name"],
                "test",
                source,
                api_only=True,
            )
            sbom_path = root / "cyclonedx.json"
            sbom_path.write_text(
                json.dumps(
                    cyclonedx_sbom(
                        contract["artifact"]["group"],
                        contract["artifact"]["name"],
                        "test",
                        aar,
                        manifest,
                    )
                ),
                encoding="utf-8",
                newline="\n",
            )
            verify_sbom(sbom_path, aar, verified)

    def test_source_allowlist_rejects_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            allowlist = Path(directory) / "sources.txt"
            allowlist.write_text("Api.kt\nApi.kt\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-empty and unique"):
                read_source_allowlist(allowlist)

    def test_module_metadata_records_exact_aar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            aar = Path(directory) / "litert-android-test.aar"
            aar.write_bytes(b"aar")
            module = gradle_module_metadata(
                "io.github.wluhwluh.bss",
                "litert-android",
                "test",
                aar,
            )
            variants = module["variants"]
            self.assertEqual(
                [variant["name"] for variant in variants],
                ["releaseApiElements", "releaseRuntimeElements"],
            )
            for variant in variants:
                self.assertEqual(variant["files"][0]["name"], aar.name)
                self.assertEqual(
                    variant["files"][0]["sha256"],
                    hashlib.sha256(b"aar").hexdigest(),
                )

    def test_sbom_lists_packaged_components(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            aar = Path(directory) / "runtime.aar"
            aar.write_bytes(b"aar")
            manifest = {
                "liteRt": {"commit": "a" * 40},
                "components": {
                    "classes.jar": {"bytes": 7, "sha256": "b" * 64},
                    "jni/x86/libLiteRt.so": {
                        "bytes": 11,
                        "sha256": "c" * 64,
                    },
                },
            }
            sbom = cyclonedx_sbom(
                "io.github.wluhwluh.bss",
                "litert-android",
                "test",
                aar,
                manifest,
            )
            self.assertEqual(sbom["specVersion"], "1.6")
            self.assertEqual(
                [component["name"] for component in sbom["components"]],
                ["classes.jar", "jni/x86/libLiteRt.so"],
            )

    def test_checksum_writer_skips_existing_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "runtime.aar"
            payload.write_bytes(b"runtime")
            (root / "runtime.aar.sha1").write_text("old\n", encoding="ascii")
            (root / "runtime.aar.asc").write_text("signature\n", encoding="ascii")

            original_argv = sys.argv
            try:
                sys.argv = ["write_maven_checksums.py", str(root)]
                self.assertEqual(write_checksums_main(), 0)
            finally:
                sys.argv = original_argv

            checksum = root / "runtime.aar.sha256"
            self.assertEqual(
                checksum.read_text(encoding="ascii").strip(),
                hashlib.sha256(b"runtime").hexdigest(),
            )
            self.assertFalse((root / "runtime.aar.sha1.sha256").exists())
            self.assertFalse((root / "runtime.aar.asc.sha256").exists())
            verify_checksums([payload])

    def test_generated_archives_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.jar"
            second = root / "second.jar"
            entries = {"Api.kt": b"class Api\n", "LICENSE": b"license\n"}
            write_archive(first, entries)
            write_archive(second, dict(reversed(list(entries.items()))))
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), sorted(entries))


if __name__ == "__main__":
    unittest.main()
