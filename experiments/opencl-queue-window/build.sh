#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
experiment_dir="${repo_root}/experiments/opencl-queue-window"
work_dir="${BSS_WORK_DIR:-${repo_root}/.work/opencl-queue-window}"
cache_dir="${BSS_CACHE_DIR:-${repo_root}/.cache/opencl-queue-window}"
dist_dir="${DIST_DIR:-${repo_root}/dist/opencl-queue-window}"

litert_version="2.1.5"
experiment_version="2.1.5-bss.oclq4"
official_aar_sha256="a162d1ddbdad87c002b7ec7eb31a703f2761335e693f292f94091b3569d8aa37"
official_accelerator_sha256="d22d9490c43a9428a6047564560dae83ce32a616658baa324b43843bfb066e89"
official_runtime_sha256="366e3e040b00692158f9f8f9105870672c93348a3d8e9024120b40045a074b0b"
ndk_version="25.1.8937393"
ndk_archive_name="android-ndk-r25b-linux.zip"
ndk_archive_sha256="403ac3e3020dd0db63a848dcaba6ceb2603bf64de90949d5c4361f848e44b005"
ndk_url="https://dl.google.com/android/repository/${ndk_archive_name}"
aar_url="https://dl.google.com/dl/android/maven2/com/google/ai/edge/litert/litert/${litert_version}/litert-${litert_version}.aar"

mkdir -p "${work_dir}" "${cache_dir}" "${dist_dir}"

for command in curl file python3 readelf sed sha256sum unzip zip; do
  command -v "${command}" >/dev/null || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

official_aar="${OFFICIAL_LITERT_AAR:-${cache_dir}/litert-${litert_version}.aar}"
if [[ ! -f "${official_aar}" ]]; then
  curl -fL --retry 3 "${aar_url}" -o "${official_aar}"
fi
echo "${official_aar_sha256}  ${official_aar}" | sha256sum -c -

if [[ -n "${ANDROID_NDK_HOME:-}" ]]; then
  ndk_dir="$(realpath "${ANDROID_NDK_HOME}")"
else
  ndk_archive="${cache_dir}/${ndk_archive_name}"
  ndk_dir="${work_dir}/android-ndk-r25b"
  if [[ ! -f "${ndk_archive}" ]]; then
    curl -fL --retry 3 "${ndk_url}" -o "${ndk_archive}"
  fi
  echo "${ndk_archive_sha256}  ${ndk_archive}" | sha256sum -c -
  if [[ ! -f "${ndk_dir}/source.properties" ]]; then
    unzip -q "${ndk_archive}" -d "${work_dir}"
  fi
fi
grep -q "Pkg.Revision = ${ndk_version}" "${ndk_dir}/source.properties" || {
  echo "Expected Android NDK ${ndk_version}: ${ndk_dir}" >&2
  exit 1
}

toolchain="${ndk_dir}/toolchains/llvm/prebuilt/linux-x86_64/bin"
cc="${toolchain}/aarch64-linux-android26-clang"
[[ -x "${cc}" ]] || {
  echo "Android arm64 compiler not found: ${cc}" >&2
  exit 1
}

native_dir="${work_dir}/native"
unpacked_dir="${work_dir}/aar"
case "$(realpath -m "${unpacked_dir}")" in
  "$(realpath "${work_dir}")"/*) ;;
  *) echo "Unsafe AAR work directory: ${unpacked_dir}" >&2; exit 1 ;;
esac
rm -rf "${native_dir}" "${unpacked_dir}"
mkdir -p "${native_dir}" "${unpacked_dir}"

"${cc}" -shared -fPIC -O2 \
  -Wl,-soname,libOpenCL.so \
  "${experiment_dir}/opencl_stub.c" \
  -o "${native_dir}/libOpenCL.so"

"${cc}" -shared -fPIC -O2 -std=c11 -fvisibility=hidden \
  -Wl,-soname,libOCLQ.so \
  -Wl,--no-as-needed "${native_dir}/libOpenCL.so" -Wl,--as-needed \
  "${experiment_dir}/opencl_queue_shim.c" \
  -ldl -llog \
  -o "${native_dir}/libOCLQ.so"

readelf -d "${native_dir}/libOCLQ.so" |
  grep -F 'Shared library: [libOpenCL.so]' >/dev/null
readelf -Ws "${native_dir}/libOCLQ.so" |
  grep -F 'clEnqueueNDRangeKernel' >/dev/null
readelf -Ws "${native_dir}/libOCLQ.so" |
  grep -F 'nativeGetQueueWindow' >/dev/null
file "${native_dir}/libOCLQ.so" | grep -F 'ARM aarch64' >/dev/null

unzip -q "${official_aar}" -d "${unpacked_dir}"
runtime="${unpacked_dir}/jni/arm64-v8a/libLiteRt.so"
echo "${official_runtime_sha256}  ${runtime}" | sha256sum -c -
runtime_patch_result="$(python3 \
  "${experiment_dir}/patch_runtime_kernel_batch.py" \
  "${runtime}" "${native_dir}/libLiteRt.so")"
IFS=: read -r runtime_patch_offset patched_runtime_sha256 \
  runtime_patch_match_bytes runtime_patch_instruction_bytes \
  runtime_patch_changed_bytes <<< "${runtime_patch_result}"
install -m 0644 "${native_dir}/libLiteRt.so" "${runtime}"

accelerator="${unpacked_dir}/jni/arm64-v8a/libLiteRtClGlAccelerator.so"
echo "${official_accelerator_sha256}  ${accelerator}" | sha256sum -c -
loader_offset="$(python3 "${experiment_dir}/patch_accelerator.py" \
  "${accelerator}" "${native_dir}/libLiteRtClGlAccelerator.so")"
install -m 0644 "${native_dir}/libLiteRtClGlAccelerator.so" "${accelerator}"
install -m 0644 "${native_dir}/libOCLQ.so" \
  "${unpacked_dir}/jni/arm64-v8a/libOCLQ.so"

maven_dir="${dist_dir}/m2/com/google/ai/edge/litert/litert/${experiment_version}"
mkdir -p "${maven_dir}"
aar_output="${maven_dir}/litert-${experiment_version}.aar"
pom_output="${maven_dir}/litert-${experiment_version}.pom"
archive_epoch=315532800
rm -f "${aar_output}" "${pom_output}"
(
  cd "${unpacked_dir}"
  find . -type f -exec touch -d "@${archive_epoch}" {} +
  find . -type f -print | LC_ALL=C sort | zip -q -X "${aar_output}" -@
)
sed "s/@EXPERIMENT_VERSION@/${experiment_version}/g" \
  "${experiment_dir}/pom.xml.template" > "${pom_output}"

patched_accelerator_sha256="$(sha256sum "${accelerator}" | cut -d' ' -f1)"
shim_sha256="$(sha256sum "${native_dir}/libOCLQ.so" | cut -d' ' -f1)"
aar_sha256="$(sha256sum "${aar_output}" | cut -d' ' -f1)"
build_script_sha256="$(sha256sum "${experiment_dir}/build.sh" | cut -d' ' -f1)"
runtime_patch_script_sha256="$(sha256sum \
  "${experiment_dir}/patch_runtime_kernel_batch.py" | cut -d' ' -f1)"
accelerator_patch_script_sha256="$(sha256sum \
  "${experiment_dir}/patch_accelerator.py" | cut -d' ' -f1)"
queue_shim_source_sha256="$(sha256sum \
  "${experiment_dir}/opencl_queue_shim.c" | cut -d' ' -f1)"

cat > "${dist_dir}/build-manifest.json" <<EOF
{
  "schemaVersion": "bss-litert-opencl-queue-experiment-v2",
  "coordinate": "com.google.ai.edge.litert:litert:${experiment_version}",
  "baseLiteRtVersion": "${litert_version}",
  "officialAarSha256": "${official_aar_sha256}",
  "experimentalAarSha256": "${aar_sha256}",
  "androidNdkVersion": "${ndk_version}",
  "androidMinApi": 26,
  "archiveEpoch": ${archive_epoch},
  "abi": "arm64-v8a",
  "runtimePatch": {
    "officialSha256": "${official_runtime_sha256}",
    "patchedSha256": "${patched_runtime_sha256}",
    "setterOffset": ${runtime_patch_offset},
    "matchedSetterBytes": ${runtime_patch_match_bytes},
    "instructionBytesRewritten": ${runtime_patch_instruction_bytes},
    "changedByteCount": ${runtime_patch_changed_bytes},
    "sourceOption": "numStepsOfCommandBufferPreparations",
    "targetOption": "kernel_batch_size",
    "targetValueOffsetBytes": 268,
    "targetEngagedOffsetBytes": 272
  },
  "acceleratorPatch": {
    "officialSha256": "${official_accelerator_sha256}",
    "patchedSha256": "${patched_accelerator_sha256}",
    "loaderStringOffset": ${loader_offset},
    "originalLibrary": "libOpenCL.so",
    "replacementLibrary": "libOCLQ.so"
  },
  "queueShim": {
    "sha256": "${shim_sha256}",
    "property": "debug.bss.opencl_queue_window",
    "minimumWindow": 1,
    "maximumWindow": 1024,
    "gate": "CompiledModel.run"
  },
  "sourceSha256": {
    "buildScript": "${build_script_sha256}",
    "runtimePatchScript": "${runtime_patch_script_sha256}",
    "acceleratorPatchScript": "${accelerator_patch_script_sha256}",
    "queueShim": "${queue_shim_source_sha256}"
  }
}
EOF

(
  cd "${dist_dir}"
  sha256sum \
    "build-manifest.json" \
    "m2/com/google/ai/edge/litert/litert/${experiment_version}/litert-${experiment_version}.aar" \
    "m2/com/google/ai/edge/litert/litert/${experiment_version}/litert-${experiment_version}.pom" \
    > SHA256SUMS
)

printf 'Experimental Maven repository: %s\n' "${dist_dir}/m2"
printf 'Experimental AAR SHA-256: %s\n' "${aar_sha256}"
