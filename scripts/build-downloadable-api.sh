#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${repo_root}/config/downloadable-api.env"

lock="${repo_root}/config/downloadable-api-source-lock.json"
patch_dir="${repo_root}/patches/downloadable-api"
work_dir="${BSS_DOWNLOADABLE_API_WORK_DIR:-${repo_root}/.work/downloadable-api}"
cache_dir="${BSS_DOWNLOADABLE_API_CACHE_DIR:-${repo_root}/.cache/downloadable-api}"
output_dir="${BSS_DOWNLOADABLE_API_OUTPUT_DIR:-${repo_root}/dist/downloadable-api}"
source_dir="${work_dir}/litert-source"
output_user_root="${BSS_DOWNLOADABLE_API_BAZEL_OUTPUT:-${work_dir}/bazel-output}"
repository_cache="${cache_dir}/bazel-repository-cache"
jobs="${BAZEL_JOBS:-4}"

for command in curl git install java javap python3 sha256sum; do
  command -v "${command}" >/dev/null || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

for directory in "${work_dir}" "${output_dir}"; do
  if [[ -d "${directory}" ]] &&
     find "${directory}" -mindepth 1 -print -quit | grep -q .; then
    echo "Build directory must be empty: ${directory}" >&2
    exit 1
  fi
done
mkdir -p "${work_dir}" "${cache_dir}" "${output_dir}" "${repository_cache}"

[[ -n "${ANDROID_HOME:-}" && -d "${ANDROID_HOME}" ]] || {
  echo "ANDROID_HOME must point to an Android SDK." >&2
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
[[ -n "${ANDROID_NDK_HOME:-}" &&
   -f "${ANDROID_NDK_HOME}/source.properties" ]] || {
  echo "ANDROID_NDK_HOME must point to Android NDK ${ANDROID_NDK_VERSION}." >&2
  exit 1
}
grep -Fq "Pkg.Revision = ${ANDROID_NDK_VERSION}" \
  "${ANDROID_NDK_HOME}/source.properties" || {
    echo "Expected Android NDK ${ANDROID_NDK_VERSION}: ${ANDROID_NDK_HOME}" >&2
    exit 1
  }
export ANDROID_NDK_ROOT="${ANDROID_NDK_HOME}"

if [[ -n "${BAZEL:-}" ]]; then
  bazel_bin="$(realpath "${BAZEL}")"
else
  bazel_bin="${cache_dir}/bazel-${BAZEL_VERSION}-linux-x86_64"
  if [[ ! -f "${bazel_bin}" ]]; then
    curl -fL --retry 3 \
      "https://github.com/bazelbuild/bazel/releases/download/${BAZEL_VERSION}/bazel-${BAZEL_VERSION}-linux-x86_64" \
      -o "${bazel_bin}"
  fi
fi
echo "${BAZEL_LINUX_X86_64_SHA256}  ${bazel_bin}" | sha256sum -c -
chmod +x "${bazel_bin}"
[[ "$("${bazel_bin}" --version)" == "bazel ${BAZEL_VERSION}" ]] || {
  echo "Expected Bazel ${BAZEL_VERSION}: ${bazel_bin}" >&2
  exit 1
}

git init "${source_dir}"
git -C "${source_dir}" remote add origin "${LITERT_REPOSITORY}"
git -C "${source_dir}" fetch --depth=1 --filter=blob:none origin "${LITERT_COMMIT}"
git -C "${source_dir}" checkout --detach FETCH_HEAD
python3 "${repo_root}/scripts/apply-complete-runtime-patches.py" \
  --source "${source_dir}" \
  --lock "${lock}" \
  --patch-dir "${patch_dir}"

locked_target="$(
  python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["build"]["target"])' \
    "${lock}"
)"
[[ "${locked_target}" == "${API_TARGET}" ]] || {
  echo "API target differs between env and source lock." >&2
  exit 1
}

bazel_startup=(
  "--output_user_root=${output_user_root}"
)
bazel_command=(
  "--repository_cache=${repository_cache}"
  "--config=android_arm64"
  "--define=extra_kt_jvm_opts=-jvm-target 17"
  "--define=public_maven_build=true"
  "--repo_env=HERMETIC_PYTHON_VERSION=${HERMETIC_PYTHON_VERSION}"
  "--jobs=${jobs}"
)

shutdown_bazel_server() {
  "${bazel_bin}" "--output_user_root=${output_user_root}" shutdown \
    >/dev/null 2>&1 || true
}
trap shutdown_bazel_server EXIT

cd "${source_dir}"
"${bazel_bin}" "${bazel_startup[@]}" build \
  "${bazel_command[@]}" "${API_TARGET}"

query="inputs('(^|/).+\\.(aar|so)$', deps(${API_TARGET}))"
binary_inputs="$(
  "${bazel_bin}" "${bazel_startup[@]}" aquery \
    "${bazel_command[@]}" --output=text "${query}"
)"
if [[ -n "${binary_inputs//[[:space:]]/}" ]]; then
  echo "Downloadable API action graph consumes a binary AAR or shared library:" >&2
  echo "${binary_inputs}" >&2
  exit 1
fi

classes_source="${source_dir}/bazel-bin/litert/kotlin/litert_bss_downloadable_api_kt.jar"
[[ -f "${classes_source}" ]] || {
  echo "Compiled API classes JAR is missing: ${classes_source}" >&2
  exit 1
}
classes_jar="${work_dir}/classes.jar"
install -m 0644 "${classes_source}" "${classes_jar}"

base_name="$(
  python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["output"]["baseAarFileName"])' \
    "${lock}"
)"
base_aar="${output_dir}/${base_name}"
python3 "${repo_root}/scripts/package_api_aar.py" \
  --classes-jar "${classes_jar}" \
  --manifest "${source_dir}/litert/kotlin/src/main/AndroidManifest.xml" \
  --output "${base_aar}"
python3 "${repo_root}/scripts/verify_downloadable_api.py" \
  --aar "${base_aar}" \
  --lock "${lock}"
install -m 0644 "${lock}" "${output_dir}/downloadable-api-source-lock.json"
python3 "${repo_root}/scripts/write_checksums.py" "${output_dir}"
(cd "${output_dir}" && sha256sum -c SHA256SUMS)

shutdown_bazel_server
trap - EXIT
printf 'Downloadable LiteRT API output: %s\n' "${output_dir}"
