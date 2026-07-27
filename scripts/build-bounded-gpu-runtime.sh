#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${repo_root}/config/bounded-gpu-runtime.env"

work_dir="${BSS_WORK_DIR:-${repo_root}/.work/bounded-gpu-runtime}"
cache_dir="${BSS_CACHE_DIR:-${repo_root}/.cache/bounded-gpu-runtime}"
dist_dir="${DIST_DIR:-${repo_root}/dist/bounded-gpu-runtime}"
runtime_dir="${repo_root}/runtime/bounded-gpu"
contract="${repo_root}/contracts/bounded-gpu-runtime-contract.json"

for command in curl file install javac python3 readelf sha256sum unzip; do
  command -v "${command}" >/dev/null || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

mkdir -p "${cache_dir}"
for target in "${work_dir}" "${dist_dir}"; do
  resolved="$(realpath -m "${target}")"
  case "${resolved}" in
    "$(realpath "${repo_root}")"/*) ;;
    *) echo "Refusing to replace path outside the repository: ${resolved}" >&2; exit 1 ;;
  esac
  rm -rf "${resolved}"
  mkdir -p "${resolved}"
done

download_verified() {
  local url="$1"
  local expected_sha256="$2"
  local output="$3"
  if [[ ! -f "${output}" ]]; then
    curl -fL --retry 3 "${url}" -o "${output}"
  fi
  echo "${expected_sha256}  ${output}" | sha256sum -c -
}

official_aar="${OFFICIAL_LITERT_AAR:-${cache_dir}/litert-${LITERT_VERSION}.aar}"
x86_runtime="${X86_LITERT_RUNTIME:-${cache_dir}/libLiteRt-${X86_RUNTIME_VERSION}-android-x86.so}"
download_verified "${OFFICIAL_AAR_URL}" "${OFFICIAL_AAR_SHA256}" "${official_aar}"
download_verified "${X86_RUNTIME_URL}" "${X86_RUNTIME_SHA256}" "${x86_runtime}"

if [[ -n "${ANDROID_NDK_HOME:-}" ]]; then
  ndk_dir="$(realpath "${ANDROID_NDK_HOME}")"
else
  ndk_archive="${cache_dir}/${ANDROID_NDK_ARCHIVE}"
  ndk_dir="${work_dir}/android-ndk-r25b"
  download_verified "${ANDROID_NDK_URL}" "${ANDROID_NDK_SHA256}" "${ndk_archive}"
  unzip -q "${ndk_archive}" -d "${work_dir}"
fi
grep -q "Pkg.Revision = ${ANDROID_NDK_VERSION}" "${ndk_dir}/source.properties" || {
  echo "Expected Android NDK ${ANDROID_NDK_VERSION}: ${ndk_dir}" >&2
  exit 1
}

unpacked="${work_dir}/official-aar"
native_dir="${work_dir}/native"
classes_dir="${work_dir}/capability-classes"
mkdir -p "${unpacked}" "${native_dir}" "${classes_dir}"
unzip -q "${official_aar}" -d "${unpacked}"

echo "${OFFICIAL_ARM64_RUNTIME_SHA256}  ${unpacked}/jni/arm64-v8a/libLiteRt.so" | sha256sum -c -
echo "${OFFICIAL_ARM64_ACCELERATOR_SHA256}  ${unpacked}/jni/arm64-v8a/libLiteRtClGlAccelerator.so" | sha256sum -c -
echo "${OFFICIAL_ARM32_RUNTIME_SHA256}  ${unpacked}/jni/armeabi-v7a/libLiteRt.so" | sha256sum -c -
echo "${OFFICIAL_X86_64_RUNTIME_SHA256}  ${unpacked}/jni/x86_64/libLiteRt.so" | sha256sum -c -

toolchain="${ndk_dir}/toolchains/llvm/prebuilt/linux-x86_64/bin"
cc="${toolchain}/aarch64-linux-android${ANDROID_MIN_API}-clang"
[[ -x "${cc}" ]] || {
  echo "Android arm64 compiler not found: ${cc}" >&2
  exit 1
}

"${cc}" -shared -fPIC -O2 \
  -Wl,-soname,libOpenCL.so \
  "${runtime_dir}/opencl_stub.c" \
  -o "${native_dir}/libOpenCL.so"
"${cc}" -shared -fPIC -O2 -std=c11 -fvisibility=hidden \
  -Wl,-soname,libBssOcl.so \
  -Wl,--no-as-needed "${native_dir}/libOpenCL.so" -Wl,--as-needed \
  "${runtime_dir}/opencl_queue_shim.c" \
  -ldl -llog \
  -o "${native_dir}/libBssOcl.so"

runtime_patch_result="$(python3 \
  "${repo_root}/experiments/opencl-queue-window/patch_runtime_kernel_batch.py" \
  "${unpacked}/jni/arm64-v8a/libLiteRt.so" \
  "${native_dir}/libLiteRt.so")"
accelerator_patch_result="$(python3 \
  "${repo_root}/scripts/patch_bounded_gpu_accelerator.py" \
  "${unpacked}/jni/arm64-v8a/libLiteRtClGlAccelerator.so" \
  "${native_dir}/libLiteRtClGlAccelerator.so")"

javac --release 8 -g:none -d "${classes_dir}" \
  "${runtime_dir}/java/io/github/wluhwluh/bss/litert/BssLiteRtRuntime.java"

readelf -d "${native_dir}/libBssOcl.so" | grep -F 'Shared library: [libOpenCL.so]' >/dev/null
readelf -d "${native_dir}/libBssOcl.so" | grep -F 'Library soname: [libBssOcl.so]' >/dev/null
readelf -Ws "${native_dir}/libBssOcl.so" | grep -F 'clEnqueueNDRangeKernel' >/dev/null
readelf -Ws "${native_dir}/libBssOcl.so" | grep -F 'nativeGetCapabilitySchemaVersion' >/dev/null
file "${native_dir}/libBssOcl.so" | grep -F 'ARM aarch64' >/dev/null

aar_output="${dist_dir}/litert-android-${ARTIFACT_VERSION}.aar"
manifest_output="${dist_dir}/build-manifest.json"
python3 "${repo_root}/scripts/package_bounded_gpu_aar.py" \
  --official-aar "${official_aar}" \
  --arm64-runtime "${native_dir}/libLiteRt.so" \
  --arm64-accelerator "${native_dir}/libLiteRtClGlAccelerator.so" \
  --arm64-shim "${native_dir}/libBssOcl.so" \
  --x86-runtime "${x86_runtime}" \
  --capability-classes "${classes_dir}" \
  --contract "${contract}" \
  --source-root "${repo_root}" \
  --runtime-patch-result "${runtime_patch_result}" \
  --accelerator-patch-result "${accelerator_patch_result}" \
  --output "${aar_output}" \
  --manifest-output "${manifest_output}"

python3 "${repo_root}/scripts/verify_bounded_gpu_aar.py" \
  --aar "${aar_output}" \
  --manifest "${manifest_output}" \
  --contract "${contract}"

python3 "${repo_root}/scripts/package_bounded_gpu_maven.py" \
  --aar "${aar_output}" \
  --pom-template "${runtime_dir}/pom.xml.template" \
  --version "${ARTIFACT_VERSION}" \
  --repository-output "${dist_dir}/m2" \
  --bundle-output "${dist_dir}/litert-android-${ARTIFACT_VERSION}-maven.zip"

cp "${contract}" "${dist_dir}/bounded-gpu-runtime-contract.json"
cp "${repo_root}/LICENSE" "${dist_dir}/LICENSE-BSS.txt"
cp "${unpacked}/LICENSE" "${dist_dir}/LICENSE-LiteRT.txt"
cp "${unpacked}/THIRD_PARTY_NOTICE.txt" "${dist_dir}/THIRD_PARTY_NOTICE-LiteRT.txt"
python3 "${repo_root}/scripts/write_checksums.py" "${dist_dir}"
(cd "${dist_dir}" && sha256sum -c SHA256SUMS)

echo "Bounded GPU AAR: ${aar_output}"
