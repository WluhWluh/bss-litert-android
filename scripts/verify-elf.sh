#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 LIBLITERT_SO LIBLITERT_JNI_SO ANDROID_NDK_DIR" >&2
    exit 2
fi

runtime_library="$(realpath "$1")"
jni_library="$(realpath "$2")"
ndk_dir="$(realpath "$3")"
readelf_bin="${ndk_dir}/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"

if [[ ! -x "${readelf_bin}" ]]; then
    echo "llvm-readelf not found: ${readelf_bin}" >&2
    exit 1
fi

verify_header() {
    local library="$1"
    local header
    header="$(${readelf_bin} -h "${library}")"
    grep -q 'Class:.*ELF32' <<< "${header}"
    grep -q 'Data:.*little endian' <<< "${header}"
    grep -q 'Type:.*DYN' <<< "${header}"
    grep -q 'Machine:.*Intel 80386' <<< "${header}"
}

verify_dependencies() {
    local library="$1"
    shift
    local allowed=(libandroid.so libc.so libdl.so liblog.so libm.so)
    local needed=()
    mapfile -t needed < <(
        "${readelf_bin}" -d "${library}" |
            sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' |
            sort -u
    )
    for dependency in "${needed[@]}"; do
        if [[ ! " ${allowed[*]} " =~ " ${dependency} " ]]; then
            echo "Unexpected dynamic dependency in ${library}: ${dependency}" >&2
            exit 1
        fi
    done
    for dependency in "$@"; do
        if [[ ! " ${needed[*]} " =~ " ${dependency} " ]]; then
            echo "Expected dependency is missing from ${library}: ${dependency}" >&2
            exit 1
        fi
    done
    if grep -Eq 'lib(EGL|GLES|OpenCL|vulkan)' <<< "${needed[*]}"; then
        echo "CPU-only x86 library depends on a GPU library: ${library}" >&2
        exit 1
    fi
    printf 'DT_NEEDED %s: %s\n' "${library}" "${needed[*]}"
}

verify_header "${runtime_library}"
verify_header "${jni_library}"
verify_dependencies "${runtime_library}" libc.so libdl.so liblog.so libm.so
verify_dependencies "${jni_library}" libandroid.so libc.so libdl.so liblog.so libm.so

runtime_symbols="$(${readelf_bin} --dyn-syms --wide "${runtime_library}")"
grep -q 'LiteRtCreateModelFromBuffer' <<< "${runtime_symbols}"
if grep -q 'Java_com_google_ai_edge_litert_CompiledModel_nativeRun' \
    <<< "${runtime_symbols}"; then
    echo "CompiledModel JNI unexpectedly remains in libLiteRt.so." >&2
    exit 1
fi

jni_symbols="$(${readelf_bin} --dyn-syms --wide "${jni_library}")"
grep -q 'Java_com_google_ai_edge_litert_Environment_nativeCreate' <<< "${jni_symbols}"
grep -q 'Java_com_google_ai_edge_litert_CompiledModel_nativeRun' <<< "${jni_symbols}"
grep -q 'Java_com_google_ai_edge_litert_TensorBuffer_nativeReadFloat' <<< "${jni_symbols}"

printf 'Verified %s\n' "${runtime_library}"
printf 'Verified %s\n' "${jni_library}"
