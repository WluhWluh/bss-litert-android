#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${repo_root}/config/release.env"

work_dir="${BSS_WORK_DIR:-${repo_root}/.work}"
cache_dir="${BSS_CACHE_DIR:-${repo_root}/.cache}"
dist_dir="${DIST_DIR:-${repo_root}/dist}"
source_dir="${LITERT_SOURCE_DIR:-${work_dir}/litert-src}"
output_user_root="${BAZEL_OUTPUT_USER_ROOT:-${work_dir}/bazel-output}"
repository_cache="${BAZEL_REPOSITORY_CACHE:-${work_dir}/bazel-repository-cache}"
jobs="${BAZEL_JOBS:-4}"

mkdir -p "${work_dir}" "${cache_dir}" "${dist_dir}"
find "${dist_dir}" -mindepth 1 -maxdepth 1 -type f -delete

for command in curl git patch python3 sha256sum unzip; do
    command -v "${command}" >/dev/null || {
        echo "Required command not found: ${command}" >&2
        exit 1
    }
done

if [[ -n "${BAZEL:-}" ]]; then
    bazel_bin="$(realpath "${BAZEL}")"
else
    bazel_bin="${cache_dir}/bazel-${BAZEL_VERSION}-linux-x86_64"
    if [[ ! -f "${bazel_bin}" ]]; then
        curl -fL --retry 3 \
            "https://github.com/bazelbuild/bazel/releases/download/${BAZEL_VERSION}/bazel-${BAZEL_VERSION}-linux-x86_64" \
            -o "${bazel_bin}"
    fi
    echo "${BAZEL_LINUX_X86_64_SHA256}  ${bazel_bin}" | sha256sum -c -
    chmod +x "${bazel_bin}"
fi
if [[ "$("${bazel_bin}" --version)" != "bazel ${BAZEL_VERSION}" ]]; then
    echo "Expected Bazel ${BAZEL_VERSION}: ${bazel_bin}" >&2
    exit 1
fi

if [[ -n "${ANDROID_NDK_HOME:-}" ]]; then
    ndk_dir="$(realpath "${ANDROID_NDK_HOME}")"
else
    ndk_archive="${cache_dir}/${ANDROID_NDK_ARCHIVE}"
    ndk_dir="${work_dir}/android-ndk-r25b"
    if [[ ! -f "${ndk_archive}" ]]; then
        curl -fL --retry 3 \
            "https://dl.google.com/android/repository/${ANDROID_NDK_ARCHIVE}" \
            -o "${ndk_archive}"
    fi
    echo "${ANDROID_NDK_SHA256}  ${ndk_archive}" | sha256sum -c -
    if [[ ! -f "${ndk_dir}/source.properties" ]]; then
        unzip -q "${ndk_archive}" -d "${work_dir}"
    fi
fi
if ! grep -q "Pkg.Revision = ${ANDROID_NDK_VERSION}" "${ndk_dir}/source.properties"; then
    echo "Expected Android NDK ${ANDROID_NDK_VERSION}: ${ndk_dir}" >&2
    exit 1
fi

if [[ -d "${source_dir}/.git" ]]; then
    actual_commit="$(git -C "${source_dir}" rev-parse HEAD)"
    if [[ "${actual_commit}" != "${LITERT_COMMIT}" ]]; then
        echo "Expected LiteRT commit ${LITERT_COMMIT}, got ${actual_commit}." >&2
        exit 1
    fi
elif [[ -n "${LITERT_SOURCE_DIR:-}" && -f "${source_dir}/WORKSPACE" ]]; then
    echo "Using explicit non-Git LiteRT source override: ${source_dir}"
else
    git clone --filter=blob:none --branch "${LITERT_TAG}" --depth 1 \
        "${LITERT_REPOSITORY}" "${source_dir}"
    actual_commit="$(git -C "${source_dir}" rev-parse HEAD)"
    if [[ "${actual_commit}" != "${LITERT_COMMIT}" ]]; then
        echo "Expected LiteRT commit ${LITERT_COMMIT}, got ${actual_commit}." >&2
        exit 1
    fi
fi

find "${source_dir}" -type f \
    \( -name BUILD -o -name 'BUILD.*' -o -name '*.bzl' -o -name '*.bazel' \
       -o -name WORKSPACE -o -name 'WORKSPACE.*' -o -name '*.sh' \) \
    -exec sed -i 's/\r$//' {} +

patch_file="${repo_root}/patches/litert-2.1.5-x86.patch"
if patch --force --reverse --dry-run --silent -d "${source_dir}" -p1 \
    < "${patch_file}" >/dev/null 2>&1; then
    :
elif patch --force --dry-run --silent -d "${source_dir}" -p1 \
    < "${patch_file}" >/dev/null 2>&1; then
    patch --force --silent -d "${source_dir}" -p1 < "${patch_file}"
else
    echo "LiteRT source does not match the expected patch state." >&2
    exit 1
fi

android_home="${work_dir}/android-sdk"
mkdir -p "${android_home}"
export ANDROID_HOME="${android_home}"
export ANDROID_NDK_HOME="${ndk_dir}"
export ANDROID_NDK_ROOT="${ndk_dir}"

cd "${source_dir}"
"${bazel_bin}" --output_user_root="${output_user_root}" build \
    --repository_cache="${repository_cache}" \
    --config=android_x86 \
    --incompatible_enable_cc_toolchain_resolution \
    --incompatible_enable_android_toolchain_resolution \
    --repo_env=HERMETIC_PYTHON_VERSION=3.11 \
    --python_path=/usr/bin/python3 \
    --//litert/build_common:build_include=cpu_only \
    --define=xnn_enable_avxvnni=false \
    --define=xnn_enable_avxvnniint8=false \
    --define=xnn_enable_avx512fp16=false \
    --define=xnn_enable_avx512amx=false \
    --jobs="${jobs}" \
    //litert/kotlin:LiteRt

built_so="$(readlink -f bazel-bin/litert/kotlin/libLiteRt.so)"
binary_name="libLiteRt-${ARTIFACT_VERSION}-android-x86.so"
install -m 0644 "${built_so}" "${dist_dir}/${binary_name}"
"${repo_root}/scripts/verify-elf.sh" "${dist_dir}/${binary_name}" "${ndk_dir}"

output_base="$(
    "${bazel_bin}" --output_user_root="${output_user_root}" info output_base
)"
python3 "${repo_root}/scripts/collect_licenses.py" \
    --external-dir "${output_base}/external" \
    --output "${work_dir}/THIRD_PARTY_LICENSES.txt"

python3 "${repo_root}/scripts/package_release.py" \
    --shared-library "${dist_dir}/${binary_name}" \
    --source-license "${source_dir}/LICENSE" \
    --third-party-licenses "${work_dir}/THIRD_PARTY_LICENSES.txt" \
    --notices "${repo_root}/THIRD_PARTY_NOTICES.md" \
    --validation-report "${repo_root}/docs/uvr-validation-2.1.5-bss.1.md" \
    --dist-dir "${dist_dir}" \
    --artifact-version "${ARTIFACT_VERSION}" \
    --litert-version "${LITERT_VERSION}" \
    --litert-commit "${LITERT_COMMIT}" \
    --bazel-version "${BAZEL_VERSION}" \
    --ndk-version "${ANDROID_NDK_VERSION}" \
    --android-api-level "${ANDROID_API_LEVEL}"

python3 "${repo_root}/scripts/write_checksums.py" "${dist_dir}"
printf 'Release artifacts: %s\n' "${dist_dir}"
