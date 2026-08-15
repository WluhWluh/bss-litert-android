from __future__ import annotations

import io
import json
import re
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

        source_patch = (
            REPO_ROOT
            / "patches/bounded-gpu-runtime"
            / "0001-map-command-buffer-option-to-kernel-batch.patch"
        ).read_text(encoding="utf-8")
        self.assertIn("gpu_options.SetKernelBatchSize(", source_patch)
        self.assertIn("Booming SS bounded GPU", source_patch)

    def test_contract_exposes_gpu_only_for_arm64(self) -> None:
        self.assertEqual(["arm64-v8a"], self.contract["gpuEligibleAbis"])
        self.assertIn(
            "libLiteRtClGlAccelerator.so",
            self.contract["nativeMatrix"]["arm64-v8a"],
        )
        for abi in ("armeabi-v7a", "x86_64", "x86"):
            self.assertEqual(
                ["libLiteRt.so", "liblitert_jni.so"],
                self.contract["nativeMatrix"][abi],
            )

    def test_release_workflow_uses_two_clean_builds_and_pinned_actions(self) -> None:
        workflow = (
            REPO_ROOT / ".github/workflows/bounded-gpu-runtime.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("tags: ['runtime-v*-bss.*']", workflow)
        self.assertIn("replica: [a, b]", workflow)
        self.assertIn("diff -rq candidates/a candidates/b", workflow)
        self.assertIn("runtime-v${ARTIFACT_VERSION}", workflow)
        uses = re.findall(r"^\s*uses:\s*[^@\s]+@([^\s#]+)", workflow, re.MULTILINE)
        self.assertGreaterEqual(len(uses), 6)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", value) for value in uses))

    def test_v220_combined_inputs_and_source_patch_are_pinned(self) -> None:
        environment = (REPO_ROOT / "config/bounded-gpu-runtime.env").read_text(
            encoding="utf-8"
        )
        build = (REPO_ROOT / "scripts/build-bounded-gpu-runtime.sh").read_text(
            encoding="utf-8"
        )

        self.assertEqual("2.2.0", self.contract["baseLiteRtVersion"])
        self.assertEqual(2, len(self.contract["combinedAarInputs"]))
        self.assertIn(
            "OFFICIAL_IMPL_AAR_SHA256="
            "624518d72f8a249711a19e9901f480e74f823ca7818260a739cb2c023024807c",
            environment,
        )
        self.assertIn(
            "OFFICIAL_API_AAR_SHA256="
            "b785714414d7af54ad1e8f4a40a382f2809b538b88a2246dcdeb9039394bc38d",
            environment,
        )
        self.assertIn("//litert/kotlin:litert_jni", build)
        self.assertIn("--implementation-aar", build)
        self.assertIn("--api-aar", build)
        self.assertNotIn("patch_runtime_kernel_batch.py", build)
        self.assertIn(
            "X86_SUPPLEMENT_SHA256="
            "5d38611018a2ce102577457b2eca188fb2bb582a51ce35c10c4aed9e392fb3bd",
            environment,
        )

    def test_packaging_combines_aars_and_removes_non_arm64_gpu(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            implementation_classes = archive_bytes(
                {"org/tensorflow/lite/Interpreter.class": b"implementation"}
            )
            implementation_aar = root / "implementation.aar"
            write_archive(
                implementation_aar,
                {
                    "AndroidManifest.xml": b"<manifest />",
                    "classes.jar": implementation_classes,
                    "jni/arm64-v8a/libLiteRt.so": b"old-arm64-runtime",
                    "jni/arm64-v8a/libLiteRtClGlAccelerator.so": b"old-accelerator",
                    "jni/armeabi-v7a/libLiteRt.so": b"arm32-runtime",
                    "jni/armeabi-v7a/libLiteRtClGlAccelerator.so": b"unbounded",
                    "jni/x86_64/libLiteRt.so": b"x86-64-runtime",
                    "jni/x86_64/libLiteRtClGlAccelerator.so": b"unbounded",
                },
            )
            api_classes = archive_bytes(
                {
                    "com/google/ai/edge/litert/CompiledModel.class": b"api",
                    "com/google/ai/edge/litert/Environment.class": b"api",
                }
            )
            api_aar = root / "api.aar"
            write_archive(
                api_aar,
                {
                    "AndroidManifest.xml": b"<manifest />",
                    "classes.jar": api_classes,
                    "jni/arm64-v8a/liblitert_jni.so": b"official-jni",
                    "jni/armeabi-v7a/liblitert_jni.so": b"arm32-jni",
                    "jni/x86_64/liblitert_jni.so": b"x86-64-jni",
                },
            )
            x86_supplement = root / "x86.aar"
            write_archive(
                x86_supplement,
                {
                    "jni/x86/libLiteRt.so": b"x86-runtime",
                    "jni/x86/liblitert_jni.so": b"x86-jni",
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
                "arm64-accelerator.so": b"libBssOcl.so patched",
                "arm64-jni.so": (
                    b"Failed to set Booming SS bounded GPU kernelBatchSize."
                ),
                "arm64-shim.so": (
                    b"2.2.0-bss.1 gpu-opencl-bounded-fp32-v1 "
                    b"nativeGetCapabilitySchemaVersion nativeGetEventWaitCount"
                ),
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
                        "--implementation-aar",
                        str(implementation_aar),
                        "--api-aar",
                        str(api_aar),
                        "--arm64-jni",
                        str(root / "arm64-jni.so"),
                        "--arm64-accelerator",
                        str(root / "arm64-accelerator.so"),
                        "--arm64-shim",
                        str(root / "arm64-shim.so"),
                        "--x86-supplement",
                        str(x86_supplement),
                        "--capability-classes",
                        str(classes),
                        "--contract",
                        str(self.contract_path),
                        "--source-root",
                        str(REPO_ROOT),
                        "--litert-source-commit",
                        "145c7523ff08d5e57ab5c582141775eea47da9c7",
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
                self.assertNotIn(
                    "jni/armeabi-v7a/libLiteRtClGlAccelerator.so", native
                )
                self.assertIn("jni/arm64-v8a/libBssOcl.so", native)
                self.assertIn("jni/x86/libLiteRt.so", native)
                self.assertIn("jni/x86/liblitert_jni.so", native)
                with zipfile.ZipFile(io.BytesIO(archive.read("classes.jar"))) as jar:
                    self.assertIn(
                        "com/google/ai/edge/litert/CompiledModel.class",
                        jar.namelist(),
                    )


if __name__ == "__main__":
    unittest.main()
