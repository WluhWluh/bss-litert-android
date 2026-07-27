#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${repo_root}/config/complete-runtime.env"

mode="available-components"
if [[ "${1:-}" == "--complete" ]]; then
  mode="complete"
elif [[ -n "${1:-}" && "${1}" != "--available-components" ]]; then
  echo "Usage: $0 [--available-components|--complete]" >&2
  exit 2
fi

work_dir="${BSS_COMPLETE_WORK_DIR:-${repo_root}/.work/complete-runtime}"
cache_dir="${BSS_COMPLETE_CACHE_DIR:-${repo_root}/.cache/complete-runtime}"
dist_dir="${BSS_COMPLETE_DIST_DIR:-${repo_root}/dist/complete-runtime}"
source_dir="${work_dir}/litert-source"
component_dir="${dist_dir}/components"
native_dir="${component_dir}/native"
action_audit_report="${dist_dir}/bazel-action-input-audit.txt"
dependency_graph="${dist_dir}/dependency-graph.txt"
output_user_root="${work_dir}/bazel-output"
repository_cache="${cache_dir}/bazel-repository-cache"
jobs="${BAZEL_JOBS:-4}"

for command in curl find git grep install javap python3 sha256sum sort; do
  command -v "${command}" >/dev/null || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

python3 "${repo_root}/scripts/verify_complete_source_lock.py" \
  --lock "${repo_root}/config/complete-runtime-source-lock.json" \
  --patch-dir "${repo_root}/patches/complete-runtime"
if [[ "${mode}" == "complete" ]]; then
  python3 "${repo_root}/scripts/verify_complete_source_lock.py" \
    --lock "${repo_root}/config/complete-runtime-source-lock.json" \
    --patch-dir "${repo_root}/patches/complete-runtime" \
    --require-gpu-source
fi

if [[ -z "${ANDROID_HOME:-}" || ! -d "${ANDROID_HOME}" ]]; then
  echo "ANDROID_HOME must point to a Linux Android SDK." >&2
  exit 1
fi
if [[ -z "${ANDROID_NDK_HOME:-}" || ! -f "${ANDROID_NDK_HOME}/source.properties" ]]; then
  echo "ANDROID_NDK_HOME must point to Android NDK ${ANDROID_NDK_VERSION}." >&2
  exit 1
fi
grep -Fq "Pkg.Revision = ${ANDROID_NDK_VERSION}" \
  "${ANDROID_NDK_HOME}/source.properties" || {
    echo "Expected Android NDK ${ANDROID_NDK_VERSION}: ${ANDROID_NDK_HOME}" >&2
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

if [[ -e "${source_dir}" ]]; then
  echo "Source directory must not already exist: ${source_dir}" >&2
  exit 1
fi
if [[ -d "${dist_dir}" ]] && find "${dist_dir}" -mindepth 1 -print -quit | grep -q .; then
  echo "Complete-runtime dist directory must be empty: ${dist_dir}" >&2
  exit 1
fi
mkdir -p "${work_dir}" "${cache_dir}" "${component_dir}" \
  "${native_dir}" "${repository_cache}"
: > "${action_audit_report}"
: > "${dependency_graph}"

bazel_bin="${BAZEL:-${cache_dir}/bazel-${BAZEL_VERSION}-linux-x86_64}"
if [[ ! -f "${bazel_bin}" ]]; then
  curl -fL --retry 3 \
    "https://github.com/bazelbuild/bazel/releases/download/${BAZEL_VERSION}/bazel-${BAZEL_VERSION}-linux-x86_64" \
    -o "${bazel_bin}"
fi
echo "${BAZEL_LINUX_X86_64_SHA256}  ${bazel_bin}" | sha256sum -c -
chmod +x "${bazel_bin}"
[[ "$("${bazel_bin}" --version)" == "bazel ${BAZEL_VERSION}" ]] || {
  echo "Unexpected Bazel version: ${bazel_bin}" >&2
  exit 1
}

git init "${source_dir}"
git -C "${source_dir}" remote add origin "${LITERT_REPOSITORY}"
git -C "${source_dir}" fetch \
  --depth=1 \
  --filter=blob:none \
  origin "${LITERT_COMMIT}"
git -C "${source_dir}" checkout --detach FETCH_HEAD
python3 "${repo_root}/scripts/apply-complete-runtime-patches.py" \
  --source "${source_dir}" \
  --lock "${repo_root}/config/complete-runtime-source-lock.json" \
  --patch-dir "${repo_root}/patches/complete-runtime"

export ANDROID_HOME
export ANDROID_NDK_HOME
export ANDROID_NDK_ROOT="${ANDROID_NDK_HOME}"

bazel_startup=(
  "--output_user_root=${output_user_root}"
)
bazel_common=(
  "--repository_cache=${repository_cache}"
  "--repo_env=HERMETIC_PYTHON_VERSION=${HERMETIC_PYTHON_VERSION}"
  "--define=litert_runtime_link_mode=dynamic"
  "--define=public_maven_build=true"
  "--jobs=${jobs}"
  "-c"
  "opt"
)

bazel_build() {
  local config="$1"
  local build_include="$2"
  local config_args=()
  shift 2
  if [[ "${config}" == "android_x86" ]]; then
    config_args=(
      "--define=xnn_enable_avxvnni=false"
      "--define=xnn_enable_avxvnniint8=false"
      "--define=xnn_enable_avx512fp16=false"
      "--define=xnn_enable_avx512amx=false"
    )
  fi
  "${bazel_bin}" "${bazel_startup[@]}" build \
    "${bazel_common[@]}" \
    "--config=${config}" \
    "--//litert/build_common:build_include=${build_include}" \
    "${config_args[@]}" \
    "$@"
}

bazel_output() {
  local config="$1"
  local build_include="$2"
  local target="$3"
  local config_args=()
  if [[ "${config}" == "android_x86" ]]; then
    config_args=(
      "--define=xnn_enable_avxvnni=false"
      "--define=xnn_enable_avxvnniint8=false"
      "--define=xnn_enable_avx512fp16=false"
      "--define=xnn_enable_avx512amx=false"
    )
  fi
  "${bazel_bin}" "${bazel_startup[@]}" cquery \
    "${bazel_common[@]}" \
    "--config=${config}" \
    "--//litert/build_common:build_include=${build_include}" \
    "${config_args[@]}" \
    --output=files "${target}"
}

audit_bazel_action_inputs() {
  local config="$1"
  local build_include="$2"
  local config_args=()
  shift 2
  if [[ "${config}" == "android_x86" ]]; then
    config_args=(
      "--define=xnn_enable_avxvnni=false"
      "--define=xnn_enable_avxvnniint8=false"
      "--define=xnn_enable_avx512fp16=false"
      "--define=xnn_enable_avx512amx=false"
    )
  fi
  local target_set="${*}"
  local query
  query="inputs('(^|/)litert/prebuilt/.*\\.(so|aar)$', deps(set(${target_set})))"
  local matches
  matches="$(
    "${bazel_bin}" "${bazel_startup[@]}" aquery \
      "${bazel_common[@]}" \
      "--config=${config}" \
      "--//litert/build_common:build_include=${build_include}" \
      "${config_args[@]}" \
      --output=text "${query}"
  )"
  if [[ -n "${matches//[[:space:]]/}" ]]; then
    echo "Bazel action graph consumes a prebuilt LiteRT binary:" >&2
    echo "${matches}" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\tclean\n' \
    "${config}" "${build_include}" "${target_set}" \
    >> "${action_audit_report}"
}

record_dependency_graph() {
  local config="$1"
  local build_include="$2"
  local config_args=()
  shift 2
  if [[ "${config}" == "android_x86" ]]; then
    config_args=(
      "--define=xnn_enable_avxvnni=false"
      "--define=xnn_enable_avxvnniint8=false"
      "--define=xnn_enable_avx512fp16=false"
      "--define=xnn_enable_avx512amx=false"
    )
  fi
  local target_set="${*}"
  printf 'CONFIG\t%s\t%s\t%s\n' \
    "${config}" "${build_include}" "${target_set}" \
    >> "${dependency_graph}"
  "${bazel_bin}" "${bazel_startup[@]}" cquery \
    "${bazel_common[@]}" \
    "--config=${config}" \
    "--//litert/build_common:build_include=${build_include}" \
    "${config_args[@]}" \
    --output=label_kind "deps(set(${target_set}))" \
    | LC_ALL=C sort \
    >> "${dependency_graph}"
}

copy_target_output() {
  local config="$1"
  local build_include="$2"
  local target="$3"
  local suffix="$4"
  local destination="$5"
  mapfile -t matches < <(
    bazel_output "${config}" "${build_include}" "${target}" |
      grep -E "${suffix}$"
  )
  if [[ "${#matches[@]}" -ne 1 || ! -f "${source_dir}/${matches[0]}" ]]; then
    printf 'Expected one %s output for %s, got: %s\n' \
      "${suffix}" "${target}" "${matches[*]:-none}" >&2
    exit 1
  fi
  install -D -m 0644 "${source_dir}/${matches[0]}" "${destination}"
}

cd "${source_dir}"
shutdown_bazel_server() {
  "${bazel_bin}" "${bazel_startup[@]}" shutdown >/dev/null 2>&1 || true
}
trap shutdown_bazel_server EXIT

bazel_build android_arm64 cpu_only //litert/kotlin:litert_bss_api_no_jni_kt
audit_bazel_action_inputs android_arm64 cpu_only \
  //litert/kotlin:litert_bss_api_no_jni_kt
record_dependency_graph android_arm64 cpu_only \
  //litert/kotlin:litert_bss_api_no_jni_kt
copy_target_output android_arm64 cpu_only \
  //litert/kotlin:litert_bss_api_no_jni_kt '\.jar' \
  "${work_dir}/litert-bss-api-classes.jar"
python3 "${repo_root}/scripts/package_api_aar.py" \
  --classes-jar "${work_dir}/litert-bss-api-classes.jar" \
  --manifest "${source_dir}/litert/kotlin/src/core/AndroidManifest.xml" \
  --output "${component_dir}/api/litert-bss-api.aar"
python3 "${repo_root}/scripts/verify-runtime-contract.py" \
  --aar "${component_dir}/api/litert-bss-api.aar" \
  --contract "${repo_root}/contracts/complete-runtime-contract.json" \
  --mode api

abis=(arm64-v8a armeabi-v7a x86_64 x86)
configs=(android_arm64 android_arm android_x86_64 android_x86)
for index in "${!abis[@]}"; do
  abi="${abis[${index}]}"
  config="${configs[${index}]}"
  build_include="cpu_only"
  if [[ "${mode}" == "complete" &&
        ( "${abi}" == "arm64-v8a" || "${abi}" == "x86_64" ) ]]; then
    build_include="gpu"
  fi
  bazel_build "${config}" "${build_include}" \
    //litert/kotlin:litert_jni \
    //litert/kotlin:LiteRt
  audit_bazel_action_inputs "${config}" "${build_include}" \
    //litert/kotlin:litert_jni \
    //litert/kotlin:LiteRt
  record_dependency_graph "${config}" "${build_include}" \
    //litert/kotlin:litert_jni \
    //litert/kotlin:LiteRt
  copy_target_output "${config}" "${build_include}" \
    //litert/kotlin:litert_jni '/liblitert_jni\.so' \
    "${native_dir}/${abi}/liblitert_jni.so"
  copy_target_output "${config}" "${build_include}" \
    //litert/kotlin:LiteRt '/libLiteRt\.so' \
    "${native_dir}/${abi}/libLiteRt.so"
done

if [[ "${mode}" == "complete" ]]; then
  gpu_abis=(arm64-v8a x86_64)
  gpu_configs=(android_arm64 android_x86_64)
  for index in "${!gpu_abis[@]}"; do
    abi="${gpu_abis[${index}]}"
    config="${gpu_configs[${index}]}"
    target="//litert/runtime/accelerators/gpu:ml_drift_cl_gl_accelerator_so"
    bazel_build "${config}" gpu "${target}"
    audit_bazel_action_inputs "${config}" gpu "${target}"
    record_dependency_graph "${config}" gpu "${target}"
    copy_target_output "${config}" gpu "${target}" \
      '/libLiteRtClGlAccelerator\.so' \
      "${native_dir}/${abi}/libLiteRtClGlAccelerator.so"
  done
fi

llvm_bin="${ANDROID_NDK_HOME}/toolchains/llvm/prebuilt/linux-x86_64/bin"
python3 "${repo_root}/scripts/verify_native_artifacts.py" \
  --native-dir "${native_dir}" \
  --contract "${repo_root}/contracts/complete-runtime-contract.json" \
  --mode "${mode}" \
  --llvm-readobj "${llvm_bin}/llvm-readobj" \
  --llvm-nm "${llvm_bin}/llvm-nm" \
  --report "${dist_dir}/native-validation.json"

output_base="$(
  "${bazel_bin}" "${bazel_startup[@]}" info \
    "${bazel_common[@]}" output_base
)"
python3 "${repo_root}/scripts/collect_licenses.py" \
  --external-dir "${output_base}/external" \
  --output "${component_dir}/THIRD_PARTY_LICENSES.txt"
install -m 0644 "${source_dir}/LICENSE" "${component_dir}/LICENSE-LiteRT.txt"
install -m 0644 "${repo_root}/THIRD_PARTY_NOTICES.md" \
  "${component_dir}/THIRD_PARTY_NOTICES.md"

python3 "${repo_root}/scripts/write_component_manifest.py" \
  --component-dir "${component_dir}" \
  --source-lock "${repo_root}/config/complete-runtime-source-lock.json" \
  --artifact-version "${ARTIFACT_VERSION}" \
  --mode "${mode}" \
  --output "${dist_dir}/component-manifest.json"

provenance_args=()
if [[ "${BSS_REQUIRE_CLEAN_BUILD:-0}" == "1" ]]; then
  provenance_args+=(--require-clean)
fi
python3 "${repo_root}/scripts/write_build_provenance.py" \
  --environment "${repo_root}/config/complete-runtime.env" \
  --source-lock "${repo_root}/config/complete-runtime-source-lock.json" \
  --contract "${repo_root}/contracts/complete-runtime-contract.json" \
  --repository "${repo_root}" \
  --source-tree "${source_dir}" \
  --dependency-graph "${dependency_graph}" \
  --bazel "${bazel_bin}" \
  --java java \
  --python python3 \
  --git git \
  --ndk-dir "${ANDROID_NDK_HOME}" \
  --android-sdk "${ANDROID_HOME}" \
  --output "${dist_dir}/build-provenance.json" \
  "${provenance_args[@]}"

if [[ "${mode}" == "complete" ]]; then
  python3 "${repo_root}/scripts/package_complete_aar.py" \
    --api-aar "${component_dir}/api/litert-bss-api.aar" \
    --native-dir "${native_dir}" \
    --contract "${repo_root}/contracts/complete-runtime-contract.json" \
    --source-lock "${repo_root}/config/complete-runtime-source-lock.json" \
    --consumer-rules "${repo_root}/packaging/consumer-rules.pro" \
    --license "${component_dir}/LICENSE-LiteRT.txt" \
    --third-party-licenses "${component_dir}/THIRD_PARTY_LICENSES.txt" \
    --notices "${component_dir}/THIRD_PARTY_NOTICES.md" \
    --artifact-version "${ARTIFACT_VERSION}" \
    --output "${dist_dir}/litert-android-${ARTIFACT_VERSION}.aar" \
    --manifest-output "${dist_dir}/build-manifest.json"
fi

candidate_aar="${component_dir}/api/litert-bss-api.aar"
if [[ "${mode}" == "complete" ]]; then
  candidate_aar="${dist_dir}/litert-android-${ARTIFACT_VERSION}.aar"
fi
python3 "${repo_root}/scripts/audit_release_inputs.py" \
  --repository "${repo_root}" \
  --source-tree "${source_dir}" \
  --component-dir "${component_dir}" \
  --component-manifest "${dist_dir}/component-manifest.json" \
  --candidate-aar "${candidate_aar}" \
  --contract "${repo_root}/contracts/complete-runtime-contract.json" \
  --source-lock "${repo_root}/config/complete-runtime-source-lock.json" \
  --mode "${mode}" \
  --report "${dist_dir}/release-input-audit.json"

shutdown_bazel_server
trap - EXIT
printf 'Complete-runtime %s output: %s\n' "${mode}" "${dist_dir}"
