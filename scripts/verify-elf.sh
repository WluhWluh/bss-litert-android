#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
    echo "Usage: $0 LIBLITERT_SO LIBLITERT_JNI_SO ANDROID_NDK_DIR [ANDROID_API]" >&2
    exit 2
fi

runtime_library="$(realpath "$1")"
jni_library="$(realpath "$2")"
ndk_dir="$(realpath "$3")"
expected_android_api="${4:-26}"
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

verify_android_api() {
    local library="$1"
    local expected_api="$2"
    local expected_byte
    local notes
    if (( expected_api < 1 || expected_api > 255 )); then
        echo "Unsupported Android API level for ELF note verification: ${expected_api}" >&2
        return 1
    fi
    printf -v expected_byte '%02x' "${expected_api}"
    notes="$("${readelf_bin}" --notes "${library}")"
    if ! grep -F '.note.android.ident' <<< "${notes}" >/dev/null || \
        ! grep -F "description data: ${expected_byte} 00 00 00" \
            <<< "${notes}" >/dev/null; then
        echo "Expected Android API ${expected_api} note: ${library}" >&2
        return 1
    fi
}

verify_android_api "${runtime_library}" "${expected_android_api}"
verify_android_api "${jni_library}" "${expected_android_api}"

"${readelf_bin}" -d "${runtime_library}" | \
    grep -F 'Library soname: [libLiteRt.so]' >/dev/null
"${readelf_bin}" -d "${jni_library}" | \
    grep -F 'Library soname: [liblitert_jni.so]' >/dev/null
for library in "${runtime_library}" "${jni_library}"; do
    if "${readelf_bin}" -lW "${library}" | \
        awk '$1 == "LOAD" && $NF != "0x4000" { exit 1 }'; then
        :
    else
        echo "Native library LOAD alignment is not 16 KiB: ${library}" >&2
        exit 1
    fi
done

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
