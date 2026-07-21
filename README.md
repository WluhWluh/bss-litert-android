# Booming SS LiteRT Android runtime builds

This repository produces an unofficial CPU-only LiteRT runtime for Android's
32-bit `x86` ABI. The official LiteRT 2.1.5 AAR supplies ARM, ARM64, and x86_64
libraries but does not include x86. Booming SS uses this build only to fill that
missing ABI.

This project is not affiliated with or endorsed by Google or the LiteRT
project. It contains no music source-separation model weights.

## Release contents

Each release publishes:

- A canonical `libLiteRt-<version>-android-x86.so` binary.
- A native-only convenience AAR with `jni/x86/libLiteRt.so`.
- SHA-256 checksums and a machine-readable build manifest.
- LiteRT and resolved third-party license files.
- Build logs, GitHub build provenance, and x86 validation reports.

The binary must be paired with the exact official Java/Kotlin API version
recorded in `build-manifest.json`. For `2.1.5-bss.1` that dependency is:

```kotlin
implementation("com.google.ai.edge.litert:litert:2.1.5")
```

For a single Android app, consume the canonical binary directly:

```text
app/src/main/jniLibs/x86/libLiteRt.so
```

Do not add `pickFirst` for this library. A duplicate x86 runtime after a future
official LiteRT upgrade should fail the build and force an explicit review.

## Reproducible build

The build is pinned in `config/release.env` and currently uses:

- LiteRT `v2.1.5` at commit
  `9d26e89d88ef8785b6a1e54ec41ac8add215a125`.
- Bazel `7.7.0`.
- Android NDK r25b (`25.1.8937393`).
- `rules_android_ndk` `0.1.3`.
- Android API level 23 and the x86 ABI.
- LiteRT's `cpu_only` build configuration.

On Ubuntu or WSL:

```bash
./scripts/build-release.sh
```

The script downloads and verifies Bazel and the NDK when they are not supplied
through `BAZEL` and `ANDROID_NDK_HOME`. Artifacts are written to `dist/`.

## Release workflow

Push a tag matching the version file to build and publish a release:

```bash
git tag v2.1.5-bss.1
git push origin v2.1.5-bss.1
```

The release workflow builds from source, verifies the ELF architecture,
dynamic dependencies, and JNI exports, runs a small model on an API 26 pure x86
emulator, generates provenance, and publishes the resulting assets.

Full 9662 and KARA validation for the first release is recorded in
`docs/uvr-validation-2.1.5-bss.1.md`. Automated UVR smoke will be enabled after
the model repository publishes immutable release URLs and hashes.

## License

Repository-authored scripts and documentation use Apache-2.0. Release binaries
are derivative builds of LiteRT and its resolved dependencies. Consult the
license and notice assets included with each release.
