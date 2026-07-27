from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from deterministic_archive import archive_bytes, write_archive  # noqa: E402


class BoundedGpuRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract_path = (
            REPO_ROOT / "contracts/bounded-gpu-runtime-contract.json"
        )
        self.contract = json.loads(self.contract_path.read_text(encoding="utf-8"))

    def test_capability_identity_is_frozen_across_contract_and_sources(self) -> None:
        capability = self.contract["capability"]
        java_source = (
            REPO_ROOT
            / "runtime/bounded-gpu/java/io/github/wluhwluh/bss/litert"
            / "BssLiteRtRuntime.java"
        ).read_text(encoding="utf-8")
        native_source = (
            REPO_ROOT / "runtime/bounded-gpu/opencl_queue_shim.c"
        ).read_text(encoding="utf-8")

        self.assertEqual("gpu-opencl-bounded-fp32-v1", capability["profileId"])
        self.assertEqual(1, capability["kernelBatchSize"])
        self.assertEqual(1, capability["commandQueueWindowSize"])
        for value in (
            capability["artifactVersion"],
            capability["profileId"],
        ):
            self.assertIn(value, java_source)
            self.assertIn(value, native_source)
        self.assertIn("KERNEL_BATCH_SIZE = 1", java_source)
        self.assertIn("COMMAND_QUEUE_WINDOW_SIZE = 1", java_source)

    def test_contract_exposes_gpu_only_for_arm64(self) -> None:
        self.assertEqual(["arm64-v8a"], self.contract["gpuEligibleAbis"])
        self.assertIn(
            "libLiteRtClGlAccelerator.so",
            self.contract["nativeMatrix"]["arm64-v8a"],
        )
        for abi in ("armeabi-v7a", "x86_64", "x86"):
            self.assertEqual(["libLiteRt.so"], self.contract["nativeMatrix"][abi])

    def test_packaging_is_deterministic_and_removes_unbounded_x86_64_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_classes = archive_bytes(
                {"com/google/ai/edge/litert/Environment.class": b"official"}
            )
            official_aar = root / "official.aar"
            write_archive(
                official_aar,
                {
                    "AndroidManifest.xml": b"<manifest />",
                    "classes.jar": original_classes,
                    "jni/arm64-v8a/libLiteRt.so": b"old-arm64-runtime",
                    "jni/arm64-v8a/libLiteRtClGlAccelerator.so": b"old-accelerator",
                    "jni/armeabi-v7a/libLiteRt.so": b"arm32-runtime",
                    "jni/x86_64/libLiteRt.so": b"x86-64-runtime",
                    "jni/x86_64/libLiteRtClGlAccelerator.so": b"unbounded",
                },
            )
            classes = root / "classes"
            capability_prefix = (
                classes / "io/github/wluhwluh/bss/litert/BssLiteRtRuntime"
            )
            capability_prefix.parent.mkdir(parents=True)
            capability_prefix.with_suffix(".class").write_bytes(b"outer")
            capability_prefix.with_name(
                capability_prefix.name + "$Capability.class"
            ).write_bytes(b"inner")
            inputs = {
                "arm64-runtime.so": b"patched-runtime",
                "arm64-accelerator.so": b"libBssOcl.so patched",
                "arm64-shim.so": (
                    b"2.1.5-bss.2 gpu-opencl-bounded-fp32-v1 "
                    b"nativeGetCapabilitySchemaVersion nativeGetEventWaitCount"
                ),
                "x86-runtime.so": b"x86-runtime",
            }
            for name, contents in inputs.items():
                (root / name).write_bytes(contents)

            outputs = []
            for index in range(2):
                output = root / f"runtime-{index}.aar"
                manifest = root / f"manifest-{index}.json"
                subprocess.run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "scripts/package_bounded_gpu_aar.py"),
                        "--official-aar",
                        str(official_aar),
                        "--arm64-runtime",
                        str(root / "arm64-runtime.so"),
                        "--arm64-accelerator",
                        str(root / "arm64-accelerator.so"),
                        "--arm64-shim",
                        str(root / "arm64-shim.so"),
                        "--x86-runtime",
                        str(root / "x86-runtime.so"),
                        "--capability-classes",
                        str(classes),
                        "--contract",
                        str(self.contract_path),
                        "--source-root",
                        str(REPO_ROOT),
                        "--runtime-patch-result",
                        "1:" + "a" * 64 + ":28:8:4",
                        "--accelerator-patch-result",
                        "2:" + "b" * 64,
                        "--output",
                        str(output),
                        "--manifest-output",
                        str(manifest),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    [
                        sys.executable,
                        str(REPO_ROOT / "scripts/verify_bounded_gpu_aar.py"),
                        "--aar",
                        str(output),
                        "--manifest",
                        str(manifest),
                        "--contract",
                        str(self.contract_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                outputs.append(output)

            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            with zipfile.ZipFile(outputs[0]) as archive:
                native = {
                    name for name in archive.namelist() if name.startswith("jni/")
                }
                self.assertNotIn(
                    "jni/x86_64/libLiteRtClGlAccelerator.so", native
                )
                self.assertIn("jni/arm64-v8a/libBssOcl.so", native)
                self.assertIn("jni/x86/libLiteRt.so", native)


if __name__ == "__main__":
    unittest.main()
