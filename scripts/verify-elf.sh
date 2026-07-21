#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 LIBLITERT_SO ANDROID_NDK_DIR" >&2
    exit 2
fi

shared_library="$(realpath "$1")"
ndk_dir="$(realpath "$2")"
readelf_bin="${ndk_dir}/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"

if [[ ! -x "${readelf_bin}" ]]; then
    echo "llvm-readelf not found: ${readelf_bin}" >&2
    exit 1
fi

header="$(${readelf_bin} -h "${shared_library}")"
grep -q 'Class:.*ELF32' <<< "${header}"
grep -q 'Data:.*little endian' <<< "${header}"
grep -q 'Type:.*DYN' <<< "${header}"
grep -q 'Machine:.*Intel 80386' <<< "${header}"

mapfile -t needed < <(
    "${readelf_bin}" -d "${shared_library}" |
        sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' |
        sort -u
)

allowed=(libandroid.so libc.so libdl.so liblog.so libm.so)
for dependency in "${needed[@]}"; do
    if [[ ! " ${allowed[*]} " =~ " ${dependency} " ]]; then
        echo "Unexpected dynamic dependency: ${dependency}" >&2
        exit 1
    fi
done
for dependency in "${allowed[@]}"; do
    if [[ ! " ${needed[*]} " =~ " ${dependency} " ]]; then
        echo "Expected dynamic dependency is missing: ${dependency}" >&2
        exit 1
    fi
done

symbols="$(${readelf_bin} --dyn-syms "${shared_library}")"
grep -q 'Java_com_google_ai_edge_litert_Environment_nativeCreate' <<< "${symbols}"
grep -q 'Java_com_google_ai_edge_litert_CompiledModel_nativeRun' <<< "${symbols}"
grep -q 'Java_com_google_ai_edge_litert_TensorBuffer_nativeReadFloat' <<< "${symbols}"
grep -q 'LiteRtCreateModelFromBuffer' <<< "${symbols}"

if grep -Eq 'lib(EGL|GLES|OpenCL|vulkan)' <<< "${needed[*]}"; then
    echo "CPU-only runtime unexpectedly depends on a GPU library." >&2
    exit 1
fi

printf 'Verified %s\n' "${shared_library}"
printf 'DT_NEEDED: %s\n' "${needed[*]}"
