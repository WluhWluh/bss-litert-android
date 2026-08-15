# LiteRT 2.2.0 supplemental Android x86 runtime

This release supplies the two native libraries that LiteRT 2.2.0 requires for
the 32-bit Android `x86` ABI. Both libraries are built from the exact upstream
`v2.2.0` source commit with a CPU-only configuration and a hash-locked SONAME
normalization patch required for app-private explicit-path loading.

## Assets

- `libLiteRt-2.2.0-bss.2-android-x86.so`: LiteRT implementation and C runtime.
- `liblitert_jni-2.2.0-bss.2-android-x86.so`: Kotlin API JNI bridge.
- `litert-2.2.0-bss.2-android-x86.aar`: native-only convenience package
  containing both libraries.
- `litert-2.2.0-x86-soname.patch`: exact hash-locked source delta applied to
  the upstream LiteRT tag.
- `SHA256SUMS`: hashes for every release asset.
- `build-manifest.json`: pinned source, toolchain, targets, and output hashes.
- License, notice, build log, and validation report files.

Use this supplement with both official LiteRT 2.2.0 artifacts. It fills the
`x86` ABI omitted from `com.google.ai.edge.litert:litert:2.2.0` and
`com.google.ai.edge.litert:litert-api:2.2.0`; it does not replace their Java,
Kotlin, ARM, or x86_64 contents.

The two x86 ELF files declare Android API 26 in `.note.android.ident`; API 26
is therefore the minimum supported Android version for this supplement.

The release workflow runs API 26 pure-x86 inference through `Environment`,
`CompiledModel`, and `TensorBuffer` in both conventional and private-core
layouts. A separate process also loads the app-private core and JNI pair by
absolute path. The private-core inference requires `DT_SONAME=libLiteRt.so`;
this corrects the `2.2.0-bss.1` supplement, whose runtime SONAME prevented JNI
from reopening a separately installed core. The unmodified upstream API still
loads the same JNI bytes from the APK for the inference phase because it
hard-codes `System.loadLibrary("litert_jni")`.
Historical UVR validation from 2.1.5 is not carried forward as evidence for
this new runtime.
