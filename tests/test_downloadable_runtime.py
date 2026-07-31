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

    def test_contract_freezes_all_cpu_abis(self) -> None:
        self.assertEqual(
            {"arm64-v8a", "armeabi-v7a", "x86_64", "x86"},
            set(self.contract["cpuCore"]["abis"]),
        )
        hashes = {
            value["sha256"] for value in self.contract["cpuCore"]["abis"].values()
        }
        self.assertEqual(4, len(hashes))
        for abi, metadata in self.contract["cpuCore"]["abis"].items():
            manifest = cpu_file_manifest(self.contract, abi, metadata)
            self.assertEqual("libLiteRt.so", manifest["path"])
            self.assertEqual(metadata["sha256"], manifest["sha256"])

    def test_x86_soname_anomaly_is_explicit(self) -> None:
        x86 = self.contract["cpuCore"]["abis"]["x86"]
        self.assertEqual("LiteRt", x86["soname"])
        self.assertNotIn("libGLESv3.so", x86["systemDependenciesOverride"])
        self.assertNotIn("libEGL.so", x86["systemDependenciesOverride"])

    def test_gpu_bundle_requires_exact_arm64_core_and_n1_profile(self) -> None:
        gpu = self.contract["boundedGpu"]
        arm64 = self.contract["cpuCore"]["abis"]["arm64-v8a"]
        self.assertEqual("arm64-v8a", gpu["abi"])
        self.assertEqual(arm64["sha256"], gpu["requiredCoreSha256"])
        self.assertEqual("gpu-opencl-bounded-fp32-v1", gpu["profile"]["profileId"])
        self.assertEqual(1, gpu["profile"]["kernelBatchSize"])
        self.assertEqual(1, gpu["profile"]["commandQueueWindowSize"])

    def test_api_and_native_sources_are_locked_independently(self) -> None:
        source = self.contract["sourceAar"]
        self.assertEqual(
            "88cd2f7eaf1443d1c570085b1c24f239db87eb24c788a590adf5158e17443d0e",
            source["sha256"],
        )
        self.assertEqual("2.1.5-bss.2", self.contract["runtimeArtifactVersion"])
        self.assertEqual(
            "bss-litert-downloadable-runtime-v2",
            self.contract["schemaVersion"],
        )
        self.assertIn("downloadable-loader", self.contract["apiAar"]["fileName"])
        self.assertEqual(
            "com.google.ai.edge.litert.LiteRtNativeLibraryLoader",
            self.contract["explicitLoader"]["className"],
        )

    def test_explicit_loader_source_patch_series_is_frozen(self) -> None:
        lock = json.loads(
            (REPO_ROOT / "config/downloadable-api-source-lock.json").read_text(
                encoding="utf-8"
            )
        )
        series = [
            line.strip()
            for line in (
                REPO_ROOT / "patches/downloadable-api/series"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(
            [entry["file"] for entry in lock["patchSeries"]],
            series,
        )
        for entry in lock["patchSeries"]:
            patch = REPO_ROOT / "patches/downloadable-api" / entry["file"]
            self.assertEqual(
                entry["sha256"],
                hashlib.sha256(patch.read_bytes()).hexdigest(),
            )
        lock_bytes = (
            REPO_ROOT / "config/downloadable-api-source-lock.json"
        ).read_bytes()
        self.assertEqual(
            self.contract["apiAar"]["sourceLockByteSize"],
            len(lock_bytes),
        )
        self.assertEqual(
            self.contract["apiAar"]["sourceLockSha256"],
            hashlib.sha256(lock_bytes).hexdigest(),
        )

    def test_source_build_separates_bazel_startup_and_command_options(self) -> None:
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
        self.assertIn("local_jdk|remotejdk[0-9]+_", script)
        self.assertIn("--include_commandline=false", script)

    def test_release_workflow_is_separate_and_pinned(self) -> None:
        workflow = (
            REPO_ROOT / ".github/workflows/downloadable-runtime.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("tags: ['downloadable-runtime-v*']", workflow)
        self.assertIn("replica: [a, b]", workflow)
        self.assertIn("diff -rq candidates/a candidates/b", workflow)
        self.assertIn("--prerelease", workflow)
        uses = re.findall(r"^\s*uses:\s*[^@\s]+@([^\s#]+)", workflow, re.MULTILINE)
        self.assertGreaterEqual(len(uses), 6)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", value) for value in uses))


if __name__ == "__main__":
    unittest.main()
