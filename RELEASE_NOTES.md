# LiteRT 2.1.5 supplemental Android x86 runtime

This is the first unofficial Booming SS supplemental build of LiteRT for the
32-bit Android `x86` ABI.

## Assets

- `libLiteRt-2.1.5-bss.1-android-x86.so`: canonical native runtime.
- `litert-2.1.5-bss.1-android-x86.aar`: native-only convenience package.
- `SHA256SUMS`: hashes for every release asset.
- `build-manifest.json`: pinned source, toolchain, and build configuration.
- License, notice, build log, and validation report files.

The binary is CPU-only and must be used with the Java/Kotlin API from
`com.google.ai.edge.litert:litert:2.1.5`. It is intended to fill the x86 ABI
missing from the official AAR; it does not replace official ARM or x86_64
libraries.

9662 and KARA passed API 26 pure x86 inference and numerical comparison. HQ4
does not fit the tested 2 GB x86 environment and remains unsupported there.
