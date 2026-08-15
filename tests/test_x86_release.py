from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class X86ReleaseTest(unittest.TestCase):
    def test_release_identity_and_split_build_are_pinned(self) -> None:
        release = (REPO_ROOT / "config/release.env").read_text(encoding="utf-8")
        build = (REPO_ROOT / "scripts/build-release.sh").read_text(
            encoding="utf-8"
        )
        workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(
            encoding="utf-8"
        )
        smoke = (REPO_ROOT / "scripts/run-x86-smoke.sh").read_text(
            encoding="utf-8"
        )
        verifier = (REPO_ROOT / "scripts/verify-elf.sh").read_text(
            encoding="utf-8"
        )
        patch = REPO_ROOT / "patches/litert-2.2.0-x86-soname.patch"

        self.assertIn("LITERT_VERSION=2.2.0", release)
        self.assertIn(
            "LITERT_COMMIT=145c7523ff08d5e57ab5c582141775eea47da9c7",
            release,
        )
        self.assertIn("ARTIFACT_VERSION=2.2.0-bss.2", release)
        self.assertIn("X86_SONAME_PATCH_SHA256=986ab875563140cb", release)
        self.assertIn("ANDROID_API_LEVEL=26", release)
        self.assertIn("git -C \"${source_dir}\" apply", build)
        self.assertIn("--untracked-files=all --ignored=matching", build)
        self.assertIn("diff does not exactly match the locked SONAME patch", build)
        self.assertIn("//litert/kotlin:LiteRt", build)
        self.assertIn("//litert/kotlin:litert_jni", build)
        self.assertNotIn("litert-2.1.5-x86.patch", build)
        self.assertIn("jniLibs/x86/libLiteRt.so", workflow)
        self.assertIn("jniLibs/x86/liblitert_jni.so", workflow)
        self.assertIn("bash scripts/run-x86-smoke.sh", workflow)
        self.assertIn("LiteRtX86PrivatePathSmokeTest", smoke)
        self.assertIn("installsLibrariesInAppPrivateStorage", smoke)
        self.assertIn("loadsPreviouslyInstalledPairByAbsolutePath", smoke)
        self.assertIn("runsAddModelWithPrivateCoreAndPackagedJni", smoke)
        self.assertIn('apk_entries="$(unzip -Z1', smoke)
        self.assertIn(".note.android.ident", verifier)
        self.assertEqual(
            hashlib.sha256(patch.read_bytes()).hexdigest(),
            "986ab875563140cbc20ccc40a62e09cc8d984b640bdb0f87e11bb2680e5188e8",
        )

    def test_package_contains_both_split_native_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dist = root / "dist"
            runtime = root / "runtime.so"
            jni = root / "jni.so"
            license_file = root / "LICENSE"
            third_party = root / "THIRD_PARTY"
            notices = root / "NOTICES"
            validation = root / "validation.md"
            runtime.write_bytes(b"runtime")
            jni.write_bytes(b"jni")
            for path in (license_file, third_party, notices, validation):
                path.write_text(path.name, encoding="utf-8")

            command = [
                sys.executable,
                str(REPO_ROOT / "scripts/package_release.py"),
                "--runtime-library",
                str(runtime),
                "--jni-library",
                str(jni),
                "--source-license",
                str(license_file),
                "--third-party-licenses",
                str(third_party),
                "--notices",
                str(notices),
                "--validation-report",
                str(validation),
                "--dist-dir",
                str(dist),
                "--artifact-version",
                "2.2.0-bss.2",
                "--litert-version",
                "2.2.0",
                "--litert-commit",
                "145c7523ff08d5e57ab5c582141775eea47da9c7",
                "--source-patch",
                str(REPO_ROOT / "patches/litert-2.2.0-x86-soname.patch"),
                "--source-patch-sha256",
                "986ab875563140cbc20ccc40a62e09cc8d984b640bdb0f87e11bb2680e5188e8",
                "--bazel-version",
                "7.7.0",
                "--ndk-version",
                "25.1.8937393",
                "--android-api-level",
                "26",
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)

            aar = dist / "litert-2.2.0-bss.2-android-x86.aar"
            first_bytes = aar.read_bytes()
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(first_bytes, aar.read_bytes())

            with zipfile.ZipFile(aar) as archive:
                self.assertIn(
                    b'<uses-sdk android:minSdkVersion="26" />',
                    archive.read("AndroidManifest.xml"),
                )
                self.assertEqual(
                    archive.read("jni/x86/libLiteRt.so"), b"runtime"
                )
                self.assertEqual(
                    archive.read("jni/x86/liblitert_jni.so"), b"jni"
                )

            manifest = json.loads(
                (dist / "build-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["build"]["targets"],
                ["//litert/kotlin:LiteRt", "//litert/kotlin:litert_jni"],
            )
            self.assertEqual(
                set(manifest["nativeLibraries"]),
                {"libLiteRt.so", "liblitert_jni.so"},
            )
            self.assertEqual(
                manifest["nativeLibraries"]["libLiteRt.so"]["soname"],
                "libLiteRt.so",
            )
            self.assertEqual(
                manifest["nativeLibraries"]["liblitert_jni.so"]["soname"],
                "liblitert_jni.so",
            )
            self.assertEqual(
                manifest["sourcePatches"],
                [{
                    "fileName": "litert-2.2.0-x86-soname.patch",
                    "sha256": "986ab875563140cbc20ccc40a62e09cc8d984b640bdb0f87e11bb2680e5188e8",
                }],
            )
            self.assertEqual(manifest["toolchain"]["androidApiLevel"], 26)
            self.assertEqual(
                (dist / "litert-2.2.0-x86-soname.patch").read_bytes(),
                (REPO_ROOT / "patches/litert-2.2.0-x86-soname.patch").read_bytes(),
            )
            self.assertEqual(
                manifest["outputs"]["litert-2.2.0-x86-soname.patch"]["sha256"],
                "986ab875563140cbc20ccc40a62e09cc8d984b640bdb0f87e11bb2680e5188e8",
            )


if __name__ == "__main__":
    unittest.main()
