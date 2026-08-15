#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${repo_root}/config/bounded-gpu-runtime.env"

work_dir="${BSS_WORK_DIR:-${repo_root}/.work/bounded-gpu-runtime}"
cache_dir="${BSS_CACHE_DIR:-${repo_root}/.cache/bounded-gpu-runtime}"
dist_dir="${DIST_DIR:-${repo_root}/dist/bounded-gpu-runtime}"
runtime_dir="${repo_root}/runtime/bounded-gpu"
contract="${repo_root}/contracts/bounded-gpu-runtime-contract.json"
source_patch="${repo_root}/patches/bounded-gpu-runtime/0001-map-command-buffer-option-to-kernel-batch.patch"
source_dir="${work_dir}/litert-source"
output_user_root="${work_dir}/bazel-output"
repository_cache="${cache_dir}/bazel-repository-cache"
jobs="${BAZEL_JOBS:-4}"

for command in curl file git install javac patch python3 readelf sha256sum strings unzip; do
  command -v "${command}" >/dev/null || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

mkdir -p "${cache_dir}" "${repository_cache}"
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

impl_aar="${OFFICIAL_LITERT_IMPL_AAR:-${cache_dir}/litert-${LITERT_VERSION}.aar}"
api_aar="${OFFICIAL_LITERT_API_AAR:-${cache_dir}/litert-api-${LITERT_VERSION}.aar}"
x86_supplement="${X86_LITERT_SUPPLEMENT:-${cache_dir}/litert-${X86_SUPPLEMENT_VERSION}-android-x86.aar}"
download_verified "${OFFICIAL_IMPL_AAR_URL}" "${OFFICIAL_IMPL_AAR_SHA256}" "${impl_aar}"
download_verified "${OFFICIAL_API_AAR_URL}" "${OFFICIAL_API_AAR_SHA256}" "${api_aar}"
download_verified "${X86_SUPPLEMENT_URL}" "${X86_SUPPLEMENT_SHA256}" "${x86_supplement}"

if [[ -n "${BAZEL:-}" ]]; then
  bazel_bin="$(realpath "${BAZEL}")"
else
  bazel_bin="${cache_dir}/bazel-${BAZEL_VERSION}-linux-x86_64"
  download_verified \
    "https://github.com/bazelbuild/bazel/releases/download/${BAZEL_VERSION}/bazel-${BAZEL_VERSION}-linux-x86_64" \
    "${BAZEL_LINUX_X86_64_SHA256}" \
    "${bazel_bin}"
  chmod +x "${bazel_bin}"
fi
[[ "$("${bazel_bin}" --version)" == "bazel ${BAZEL_VERSION}" ]] || {
  echo "Expected Bazel ${BAZEL_VERSION}: ${bazel_bin}" >&2
  exit 1
}

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

git init "${source_dir}"
git -C "${source_dir}" remote add origin "${LITERT_REPOSITORY}"
git -C "${source_dir}" fetch --depth=1 --filter=blob:none origin "${LITERT_COMMIT}"
git -C "${source_dir}" checkout --detach FETCH_HEAD
actual_commit="$(git -C "${source_dir}" rev-parse HEAD)"
[[ "${actual_commit}" == "${LITERT_COMMIT}" ]] || {
  echo "Expected LiteRT commit ${LITERT_COMMIT}, got ${actual_commit}." >&2
  exit 1
}
patch --force --dry-run --silent -d "${source_dir}" -p1 < "${source_patch}"
patch --force --silent -d "${source_dir}" -p1 < "${source_patch}"

[[ -n "${ANDROID_HOME:-}" && -d "${ANDROID_HOME}" ]] || {
  echo "ANDROID_HOME must point to a Linux Android SDK." >&2
  exit 1
}
[[ -f "${ANDROID_HOME}/platforms/android-${ANDROID_COMPILE_SDK}/android.jar" ]] || {
  echo "Android platform ${ANDROID_COMPILE_SDK} is not installed." >&2
  exit 1
}
[[ -x "${ANDROID_HOME}/build-tools/${ANDROID_BUILD_TOOLS_VERSION}/aapt2" ]] || {
  echo "Android build tools ${ANDROID_BUILD_TOOLS_VERSION} are not installed." >&2
  exit 1
}
export ANDROID_HOME
export ANDROID_NDK_HOME="${ndk_dir}"
export ANDROID_NDK_ROOT="${ndk_dir}"

bazel_startup=("--output_user_root=${output_user_root}")
bazel_command=(
  "--repository_cache=${repository_cache}"
  "--config=android_arm64"
  "--incompatible_enable_cc_toolchain_resolution"
  "--incompatible_enable_android_toolchain_resolution"
  "--repo_env=HERMETIC_PYTHON_VERSION=3.11"
  "--python_path=/usr/bin/python3"
  "--//litert/build_common:build_include=cpu_only"
  "--define=public_maven_build=true"
  "--jobs=${jobs}"
)
shutdown_bazel_server() {
  "${bazel_bin}" "${bazel_startup[@]}" shutdown >/dev/null 2>&1 || true
}
trap shutdown_bazel_server EXIT
(
  cd "${source_dir}"
  "${bazel_bin}" "${bazel_startup[@]}" build \
    "${bazel_command[@]}" //litert/kotlin:litert_jni
)

impl_unpacked="${work_dir}/implementation-aar"
api_unpacked="${work_dir}/api-aar"
x86_unpacked="${work_dir}/x86-supplement"
native_dir="${work_dir}/native"
classes_dir="${work_dir}/capability-classes"
mkdir -p "${impl_unpacked}" "${api_unpacked}" "${x86_unpacked}" \
  "${native_dir}" "${classes_dir}"
unzip -q "${impl_aar}" -d "${impl_unpacked}"
unzip -q "${api_aar}" -d "${api_unpacked}"
unzip -q "${x86_supplement}" -d "${x86_unpacked}"

echo "${OFFICIAL_ARM64_RUNTIME_SHA256}  ${impl_unpacked}/jni/arm64-v8a/libLiteRt.so" | sha256sum -c -
echo "${OFFICIAL_ARM64_ACCELERATOR_SHA256}  ${impl_unpacked}/jni/arm64-v8a/libLiteRtClGlAccelerator.so" | sha256sum -c -
echo "${OFFICIAL_ARM64_JNI_SHA256}  ${api_unpacked}/jni/arm64-v8a/liblitert_jni.so" | sha256sum -c -
echo "${OFFICIAL_ARM32_RUNTIME_SHA256}  ${impl_unpacked}/jni/armeabi-v7a/libLiteRt.so" | sha256sum -c -
echo "${OFFICIAL_ARM32_JNI_SHA256}  ${api_unpacked}/jni/armeabi-v7a/liblitert_jni.so" | sha256sum -c -
echo "${OFFICIAL_X86_64_RUNTIME_SHA256}  ${impl_unpacked}/jni/x86_64/libLiteRt.so" | sha256sum -c -
echo "${OFFICIAL_X86_64_JNI_SHA256}  ${api_unpacked}/jni/x86_64/liblitert_jni.so" | sha256sum -c -

install -m 0644 \
  "${source_dir}/bazel-bin/litert/kotlin/liblitert_jni.so" \
  "${native_dir}/liblitert_jni.so"
strings "${native_dir}/liblitert_jni.so" | \
  grep -F 'Failed to set Booming SS bounded GPU kernelBatchSize.' >/dev/null

toolchain="${ndk_dir}/toolchains/llvm/prebuilt/linux-x86_64/bin"
cc="${toolchain}/aarch64-linux-android${ANDROID_MIN_API}-clang"
[[ -x "${cc}" ]] || {
  echo "Android arm64 compiler not found: ${cc}" >&2
  exit 1
}
page_size_linkopts=(-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384)
"${cc}" -shared -fPIC -O2 "${page_size_linkopts[@]}" \
  -Wl,-soname,libOpenCL.so \
  "${runtime_dir}/opencl_stub.c" \
  -o "${native_dir}/libOpenCL.so"
"${cc}" -shared -fPIC -O2 -std=c11 -fvisibility=hidden \
  "${page_size_linkopts[@]}" \
  -Wl,-soname,libBssOcl.so \
  -Wl,--no-as-needed "${native_dir}/libOpenCL.so" -Wl,--as-needed \
  "${runtime_dir}/opencl_queue_shim.c" \
  -ldl -llog \
  -o "${native_dir}/libBssOcl.so"

accelerator_patch_result="$(python3 \
  "${repo_root}/scripts/patch_bounded_gpu_accelerator.py" \
  "${impl_unpacked}/jni/arm64-v8a/libLiteRtClGlAccelerator.so" \
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
  --implementation-aar "${impl_aar}" \
  --api-aar "${api_aar}" \
  --arm64-jni "${native_dir}/liblitert_jni.so" \
  --arm64-accelerator "${native_dir}/libLiteRtClGlAccelerator.so" \
  --arm64-shim "${native_dir}/libBssOcl.so" \
  --x86-supplement "${x86_supplement}" \
  --capability-classes "${classes_dir}" \
  --contract "${contract}" \
  --source-root "${repo_root}" \
  --litert-source-commit "${actual_commit}" \
  --accelerator-patch-result "${accelerator_patch_result}" \
  --output "${aar_output}" \
  --manifest-output "${manifest_output}"

python3 "${repo_root}/scripts/verify_bounded_gpu_aar.py" \
  --aar "${aar_output}" \
  --manifest "${manifest_output}" \
  --contract "${contract}" \
  --readelf "${toolchain}/llvm-readelf"

python3 "${repo_root}/scripts/package_bounded_gpu_maven.py" \
  --aar "${aar_output}" \
  --pom-template "${runtime_dir}/pom.xml.template" \
  --version "${ARTIFACT_VERSION}" \
  --repository-output "${dist_dir}/m2" \
  --bundle-output "${dist_dir}/litert-android-${ARTIFACT_VERSION}-maven.zip"

cp "${contract}" "${dist_dir}/bounded-gpu-runtime-contract.json"
cp "${repo_root}/LICENSE" "${dist_dir}/LICENSE-BSS.txt"
cp "${impl_unpacked}/LICENSE" "${dist_dir}/LICENSE-LiteRT.txt"
cp "${impl_unpacked}/THIRD_PARTY_NOTICE.txt" "${dist_dir}/THIRD_PARTY_NOTICE-LiteRT.txt"
python3 "${repo_root}/scripts/write_checksums.py" "${dist_dir}"
(cd "${dist_dir}" && sha256sum -c SHA256SUMS)

shutdown_bazel_server
trap - EXIT
echo "Bounded GPU AAR: ${aar_output}"
