# LiteRT 2.2.0 supplemental Android x86 runtime

This release supplies the two native libraries that LiteRT 2.2.0 requires for
the 32-bit Android `x86` ABI. Both libraries are built from the exact upstream
`v2.2.0` source commit with a CPU-only configuration.

## Assets

- `libLiteRt-2.2.0-bss.1-android-x86.so`: LiteRT implementation and C runtime.
- `liblitert_jni-2.2.0-bss.1-android-x86.so`: Kotlin API JNI bridge.
- `litert-2.2.0-bss.1-android-x86.aar`: native-only convenience package
  containing both libraries.
- `SHA256SUMS`: hashes for every release asset.
- `build-manifest.json`: pinned source, toolchain, targets, and output hashes.
- License, notice, build log, and validation report files.

Use this supplement with both official LiteRT 2.2.0 artifacts. It fills the
`x86` ABI omitted from `com.google.ai.edge.litert:litert:2.2.0` and
`com.google.ai.edge.litert:litert-api:2.2.0`; it does not replace their Java,
Kotlin, ARM, or x86_64 contents.

The release workflow runs an API 26 pure-x86 emulator inference test through
`Environment`, `CompiledModel`, and `TensorBuffer`. Historical UVR validation
from 2.1.5 is not carried forward as evidence for this new runtime.
