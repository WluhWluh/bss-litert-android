#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${repo_root}/config/complete-runtime.env"

usage() {
  cat >&2 <<'EOF'
Usage: stage-maven-publication.sh --runtime-dist DIR --litert-source DIR
                                  --output-dir DIR [--allow-api-only]
EOF
  exit 2
}

runtime_dist=""
litert_source=""
output_dir=""
allow_api_only=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-dist)
      runtime_dist="$2"
      shift 2
      ;;
    --litert-source)
      litert_source="$2"
      shift 2
      ;;
    --output-dir)
      output_dir="$2"
      shift 2
      ;;
    --allow-api-only)
      allow_api_only=true
      shift
      ;;
    *) usage ;;
  esac
done

[[ -n "${runtime_dist}" && -n "${litert_source}" && -n "${output_dir}" ]] || usage
runtime_dist="$(realpath "${runtime_dist}")"
litert_source="$(realpath "${litert_source}")"
mkdir -p "${output_dir}"
output_dir="$(realpath "${output_dir}")"
if find "${output_dir}" -mindepth 1 -print -quit | grep -q .; then
  echo "Maven output directory must be empty: ${output_dir}" >&2
  exit 1
fi

component_dir="${runtime_dist}/components"
input_dir="${output_dir}/inputs"
repository_dir="${output_dir}/repository"
prepare_args=()
verify_args=()
if [[ "${allow_api_only}" == true ]]; then
  aar="${component_dir}/api/litert-bss-api.aar"
  build_manifest="${runtime_dist}/component-manifest.json"
  prepare_args+=(--allow-api-only)
  verify_args+=(--allow-api-only)
else
  aar="${runtime_dist}/litert-android-${ARTIFACT_VERSION}.aar"
  build_manifest="${runtime_dist}/build-manifest.json"
fi

python3 "${repo_root}/scripts/prepare_maven_publication.py" \
  --aar "${aar}" \
  --api-source-root \
    "${litert_source}/litert/kotlin/src/main/kotlin" \
  --source-files "${repo_root}/contracts/api-source-files.txt" \
  --contract "${repo_root}/contracts/complete-runtime-contract.json" \
  --build-manifest "${build_manifest}" \
  --license "${component_dir}/LICENSE-LiteRT.txt" \
  --third-party-licenses "${component_dir}/THIRD_PARTY_LICENSES.txt" \
  --notices "${component_dir}/THIRD_PARTY_NOTICES.md" \
  --artifact-version "${ARTIFACT_VERSION}" \
  --output-dir "${input_dir}" \
  "${prepare_args[@]}"

"${repo_root}/smoke/gradlew" \
  -p "${repo_root}/publication" \
  publishLitertAndroidPublicationToLocalStagingRepository \
  "-PartifactVersion=${ARTIFACT_VERSION}" \
  "-PpublicationInputDir=${input_dir}" \
  "-PstagingRepositoryDir=${repository_dir}" \
  --no-daemon

version_dir="${repository_dir}/${MAVEN_GROUP//.//}/${MAVEN_ARTIFACT}/${ARTIFACT_VERSION}"
python3 "${repo_root}/scripts/write_maven_checksums.py" "${version_dir}"

signature_args=()
if [[ -n "${MAVEN_SIGNING_KEY:-}" ]]; then
  signature_args+=(--require-signatures)
fi
python3 "${repo_root}/scripts/verify_maven_staging.py" \
  --repository "${repository_dir}" \
  --contract "${repo_root}/contracts/complete-runtime-contract.json" \
  --source-files "${repo_root}/contracts/api-source-files.txt" \
  --group "${MAVEN_GROUP}" \
  --artifact "${MAVEN_ARTIFACT}" \
  --version "${ARTIFACT_VERSION}" \
  "${verify_args[@]}" \
  "${signature_args[@]}"

export ORG_GRADLE_PROJECT_litertStagingRepository="${repository_dir}"
export ORG_GRADLE_PROJECT_litertStagingVersion="${ARTIFACT_VERSION}"
"${repo_root}/smoke/gradlew" \
  -p "${repo_root}/smoke" \
  :contract:compileDebugKotlin \
  --no-daemon

printf 'Maven staging repository: %s\n' "${repository_dir}"
