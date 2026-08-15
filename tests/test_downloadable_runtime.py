from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_downloadable_runtime_bundles import cpu_file_manifest  # noqa: E402


class DownloadableRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(
            (REPO_ROOT / "contracts/downloadable-runtime-contract.json").read_text(
                encoding="utf-8"
            )
        )

    def test_contract_freezes_split_cpu_runtime_for_all_abis(self) -> None:
        cpu = self.contract["cpuCore"]
        self.assertEqual(
            {"arm64-v8a", "armeabi-v7a", "x86_64", "x86"},
            set(cpu["abis"]),
        )
        self.assertEqual(2, cpu["componentManifestSchemaVersion"])
        self.assertEqual(["libLiteRt.so", "liblitert_jni.so"], cpu["loadOrder"])
        hashes = set()
        for abi, metadata in cpu["abis"].items():
            self.assertEqual(
                ["runtime", "jni"],
                [file_metadata["role"] for file_metadata in metadata["files"]],
                abi,
            )
            self.assertEqual(
                cpu["loadOrder"],
                [file_metadata["path"] for file_metadata in metadata["files"]],
                abi,
            )
            for file_metadata in metadata["files"]:
                manifest = cpu_file_manifest(self.contract, abi, file_metadata)
                self.assertEqual(file_metadata["path"], manifest["path"])
                self.assertEqual(file_metadata["role"], manifest["role"])
                self.assertEqual(file_metadata["sha256"], manifest["sha256"])
                self.assertEqual(16384, manifest["elf"]["loadAlignment"])
                if file_metadata["role"] == "jni":
                    self.assertEqual(["libLiteRt.so"], manifest["runtimeLoads"])
                hashes.add(file_metadata["sha256"])
        self.assertEqual(8, len(hashes))

    def test_per_abi_soname_and_dependency_anomalies_are_explicit(self) -> None:
        cpu = self.contract["cpuCore"]["abis"]
        x86_runtime, x86_jni = cpu["x86"]["files"]
        arm64_runtime, arm64_jni = cpu["arm64-v8a"]["files"]
        self.assertEqual("LiteRt", x86_runtime["soname"])
        self.assertEqual("litert_jni", x86_jni["soname"])
        self.assertEqual("libLiteRt.so", arm64_runtime["soname"])
        self.assertEqual("litert_jni", arm64_jni["soname"])
        self.assertNotIn("libGLESv3.so", x86_runtime["needed"])
        self.assertNotIn("libEGL.so", x86_runtime["needed"])
        self.assertIn("libGLESv3.so", arm64_runtime["needed"])

    def test_gpu_bundle_requires_exact_arm64_runtime_and_jni(self) -> None:
        gpu = self.contract["boundedGpu"]
        arm64_files = {
            value["role"]: value
            for value in self.contract["cpuCore"]["abis"]["arm64-v8a"]["files"]
        }
        self.assertEqual("arm64-v8a", gpu["abi"])
        self.assertEqual("arm64-v8a", gpu["requiredCore"]["abi"])
        self.assertEqual(
            arm64_files["runtime"]["sha256"],
            gpu["requiredCore"]["librarySha256"],
        )
        self.assertEqual(
            arm64_files["jni"]["sha256"],
            gpu["requiredCore"]["jniLibrarySha256"],
        )
        self.assertEqual("gpu-opencl-bounded-fp32-v1", gpu["profile"]["profileId"])
        self.assertEqual(1, gpu["profile"]["kernelBatchSize"])
        self.assertEqual(1, gpu["profile"]["commandQueueWindowSize"])

    def test_api_and_native_sources_are_locked_independently(self) -> None:
        source = self.contract["sourceAar"]
        self.assertEqual(
            "20b4cf61a4cb5894c3f4d6540c09898743b6f5f7ea5d95c5fa9fb22aa54c288f",
            source["sha256"],
        )
        self.assertEqual("2.2.0-bss.1", self.contract["runtimeArtifactVersion"])
        self.assertEqual(
            "bss-litert-downloadable-runtime-v3",
            self.contract["schemaVersion"],
        )
        self.assertIn("downloadable-loader", self.contract["apiAar"]["fileName"])
        loader = self.contract["explicitLoader"]
        self.assertEqual(
            "com.google.ai.edge.litert.LiteRtNativeLibraryLoader",
            loader["className"],
        )
        self.assertEqual("runtime", loader["configurationPathRole"])
        self.assertEqual(
            self.contract["cpuCore"]["loadOrder"],
            loader["absolutePathLoadOrder"],
        )

    def test_explicit_loader_source_patch_series_and_output_are_frozen(self) -> None:
        lock_path = REPO_ROOT / "config/downloadable-api-source-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        series = [
            line.strip()
            for line in (REPO_ROOT / "patches/downloadable-api/series")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.assertEqual([entry["file"] for entry in lock["patchSeries"]], series)
        for entry in lock["patchSeries"]:
            patch = REPO_ROOT / "patches/downloadable-api" / entry["file"]
            self.assertEqual(
                entry["sha256"],
                hashlib.sha256(patch.read_bytes()).hexdigest(),
            )
        lock_bytes = lock_path.read_bytes()
        self.assertEqual(self.contract["apiAar"]["sourceLockByteSize"], len(lock_bytes))
        self.assertEqual(
            self.contract["apiAar"]["sourceLockSha256"],
            hashlib.sha256(lock_bytes).hexdigest(),
        )
        self.assertEqual(
            self.contract["apiAar"]["baseSha256"],
            lock["output"]["baseAarSha256"],
        )
        self.assertEqual(
            self.contract["apiAar"]["classesJarSha256"],
            lock["output"]["classesJarSha256"],
        )

    def test_loader_patch_freezes_core_then_jni_order_and_fallback(self) -> None:
        patch = (
            REPO_ROOT
            / "patches/downloadable-api/0001-explicit-split-native-loader.patch"
        ).read_text(encoding="utf-8")
        runtime_load = patch.index("System.load(runtimePath);")
        jni_load = patch.index("System.load(jniPath);")
        self.assertLess(runtime_load, jni_load)
        self.assertIn('System.loadLibrary(DEFAULT_JNI_LIBRARY_NAME);', patch)
        self.assertIn('JNI_LIBRARY_FILE_NAME = "liblitert_jni.so"', patch)
        self.assertIn('RUNTIME_LIBRARY_FILE_NAME = "libLiteRt.so"', patch)

    def test_source_build_separates_bazel_options_and_audits_host_tools(self) -> None:
        script = (REPO_ROOT / "scripts/build-downloadable-api.sh").read_text(
            encoding="utf-8"
        )
        startup = script.split("bazel_startup=(", 1)[1].split(")", 1)[0]
        command = script.split("bazel_command=(", 1)[1].split(")", 1)[0]
        self.assertIn("--output_user_root=", startup)
        self.assertNotIn("--repository_cache=", startup)
        self.assertIn("--repository_cache=", command)
        self.assertIn(
            '"${bazel_bin}" "${bazel_startup[@]}" build \\\n'
            '  "${bazel_command[@]}" "${API_TARGET}"',
            script,
        )
        self.assertIn("unexpected_binary_inputs", script)
        self.assertIn("llvm18_linux_x86_64", script)
        self.assertIn("sysroot_linux_x86_64_glibc_2_27", script)
        self.assertIn("--include_commandline=false", script)
        self.assertIn("PACKAGING_PYTHON_VERSION", script)
        self.assertIn("PACKAGING_ZLIB_VERSION", script)

    def test_release_workflow_is_separate_reproducible_and_pinned(self) -> None:
        workflow = (
            REPO_ROOT / ".github/workflows/downloadable-runtime.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("tags: ['downloadable-runtime-v*']", workflow)
        self.assertIn("replica: [a, b]", workflow)
        self.assertIn("diff -rq candidates/a candidates/b", workflow)
        self.assertIn("build-downloadable-api.sh", workflow)
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        self.assertIn("python-version: '3.12.3'", workflow)
        self.assertIn("--prerelease", workflow)
        uses = re.findall(r"^\s*uses:\s*[^@\s]+@([^\s#]+)", workflow, re.MULTILINE)
        self.assertGreaterEqual(len(uses), 6)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", value) for value in uses))


if __name__ == "__main__":
    unittest.main()
