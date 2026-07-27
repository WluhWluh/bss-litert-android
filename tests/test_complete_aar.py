from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from deterministic_archive import FIXED_ZIP_TIME, write_archive  # noqa: E402
from package_complete_aar import (  # noqa: E402
    build_manifest,
    expected_native_entries,
    read_api_entries,
    read_native_entries,
)
from package_api_aar import read_classes_jar  # noqa: E402


class CompleteAarPackagingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(
            (REPO_ROOT / "contracts/complete-runtime-contract.json").read_text(
                encoding="utf-8"
            )
        )

    def test_rejects_incomplete_native_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "Missing native libraries"):
                read_native_entries(
                    root,
                    expected_native_entries(self.contract),
                )

    def test_rejects_native_code_in_api_aar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api_aar = Path(directory) / "api.aar"
            write_archive(
                api_aar,
                {
                    "AndroidManifest.xml": b"<manifest />",
                    "classes.jar": b"jar",
                    "jni/x86/liblitert_jni.so": b"native",
                },
            )
            with self.assertRaisesRegex(ValueError, "contains native code"):
                read_api_entries(api_aar)

    def test_rejects_empty_compiled_classes_jar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            classes_jar = Path(directory) / "classes.jar"
            write_archive(
                classes_jar,
                {"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n"},
            )
            with self.assertRaisesRegex(ValueError, "contains no class files"):
                read_classes_jar(classes_jar)

    def test_api_aar_is_reproducible_and_normalizes_classes_jar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            classes_jar = root / "input.jar"
            write_archive(
                classes_jar,
                {
                    "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
                    "com/example/Api.class": b"\xca\xfe\xba\xbeclass",
                },
            )
            manifest = root / "AndroidManifest.xml"
            manifest.write_text("<manifest />\n", encoding="ascii")

            outputs = []
            for index in range(2):
                output = root / f"api-{index}.aar"
                subprocess.run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "scripts/package_api_aar.py"),
                        "--classes-jar",
                        str(classes_jar),
                        "--manifest",
                        str(manifest),
                        "--output",
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                outputs.append(output)

            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            with zipfile.ZipFile(outputs[0]) as aar:
                with zipfile.ZipFile(io.BytesIO(aar.read("classes.jar"))) as jar:
                    self.assertEqual(jar.namelist(), sorted(jar.namelist()))
                    for info in jar.infolist():
                        self.assertEqual(info.date_time, FIXED_ZIP_TIME)

    def test_archive_is_sorted_normalized_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = {
                "classes.jar": b"classes",
                "AndroidManifest.xml": b"<manifest />",
                "jni/x86/libLiteRt.so": b"runtime",
            }
            first = root / "first.aar"
            second = root / "second.aar"
            write_archive(first, entries)
            write_archive(second, dict(reversed(list(entries.items()))))
            self.assertEqual(first.read_bytes(), second.read_bytes())

            with zipfile.ZipFile(first) as archive:
                self.assertEqual(
                    archive.namelist(),
                    sorted(archive.namelist()),
                )
                for info in archive.infolist():
                    self.assertEqual(info.date_time, FIXED_ZIP_TIME)
                    self.assertEqual(info.external_attr >> 16, 0o100644)

    def test_manifest_records_only_publishable_components(self) -> None:
        source_lock = json.loads(
            (
                REPO_ROOT / "config/complete-runtime-source-lock.json"
            ).read_text(encoding="utf-8")
        )
        manifest = build_manifest(
            "test-version",
            self.contract,
            source_lock,
            {
                "AndroidManifest.xml": b"manifest",
                "classes.jar": b"classes",
                "jni/x86/libLiteRt.so": b"runtime",
            },
        )
        self.assertEqual(
            set(manifest["components"]),
            {"classes.jar", "jni/x86/libLiteRt.so"},
        )

    def test_cli_assembles_complete_matrix_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            api_aar = root / "api.aar"
            write_archive(
                api_aar,
                {
                    "AndroidManifest.xml": b"<manifest />",
                    "classes.jar": b"classes",
                },
            )
            native_dir = root / "native"
            for relative in expected_native_entries(self.contract).values():
                native = native_dir / relative
                native.parent.mkdir(parents=True, exist_ok=True)
                native.write_bytes(f"native:{relative.as_posix()}".encode())

            text_inputs = {}
            for name in ("consumer.pro", "LICENSE", "licenses.txt", "notices.md"):
                path = root / name
                path.write_text(name + "\n", encoding="ascii", newline="\n")
                text_inputs[name] = path

            outputs = []
            for index in range(2):
                output = root / f"complete-{index}.aar"
                manifest = root / f"manifest-{index}.json"
                subprocess.run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "scripts/package_complete_aar.py"),
                        "--api-aar",
                        str(api_aar),
                        "--native-dir",
                        str(native_dir),
                        "--contract",
                        str(REPO_ROOT / "contracts/complete-runtime-contract.json"),
                        "--source-lock",
                        str(
                            REPO_ROOT
                            / "config/complete-runtime-source-lock.json"
                        ),
                        "--consumer-rules",
                        str(text_inputs["consumer.pro"]),
                        "--license",
                        str(text_inputs["LICENSE"]),
                        "--third-party-licenses",
                        str(text_inputs["licenses.txt"]),
                        "--notices",
                        str(text_inputs["notices.md"]),
                        "--artifact-version",
                        "test-version",
                        "--output",
                        str(output),
                        "--manifest-output",
                        str(manifest),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                outputs.append(output)

            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            with zipfile.ZipFile(outputs[0]) as archive:
                self.assertEqual(
                    {
                        name
                        for name in archive.namelist()
                        if name.startswith("jni/")
                    },
                    set(expected_native_entries(self.contract)),
                )


if __name__ == "__main__":
    unittest.main()
