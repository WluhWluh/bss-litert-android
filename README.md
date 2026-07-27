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

## Complete runtime roadmap

The current release remains an x86-only supplement to the official LiteRT AAR.
Future work will replace that split dependency with one source-built,
multi-ABI runtime published through Maven Central. The
[complete runtime and Maven Central roadmap](docs/complete-runtime-maven-roadmap.md)
records the artifact contract, upstream GPU source gate, reproducibility and
F-Droid requirements, device matrix, and staged Booming SS migration.

The [complete runtime source patch guide](docs/complete-runtime-source-patches.md)
documents the locked, zero-offset patch series and the unresolved public
ML Drift source requirement.

Phases 2 through 6 are the current infrastructure priority. They may build
commit-pinned alpha artifacts, but no stable complete-runtime release will be
published until an upstream stable tag contains the source-buildable GPU
accelerator.

The source-available CPU and API matrix can be built with:

```bash
./scripts/build-complete-runtime.sh --available-components
```

`--complete` additionally requires the locked public ML Drift source and
fails before fetching or compiling when that source gate is not satisfied.

## Maven staging

The publication project prepares the future coordinate without contacting
Maven Central. Given a complete-runtime build directory and its checked-out
LiteRT source, run:

```bash
./scripts/stage-maven-publication.sh \
  --runtime-dist dist/complete-runtime \
  --litert-source .work/complete-runtime/litert-source \
  --output-dir dist/maven-staging
```

The script prepares deterministic AAR, source, API documentation, SBOM,
manifest, notice, POM, and Gradle metadata files; stages them in a local Maven
repository; validates the payload; and compiles the Kotlin consumer fixture by
resolving `io.github.wluhwluh.bss:litert-android` from that repository.

Set `MAVEN_SIGNING_KEY` and `MAVEN_SIGNING_PASSWORD` to add detached OpenPGP
signatures. Unsigned staging is supported only for local and CI validation.
Until source-buildable GPU inputs are available, the manual complete-runtime
workflow uses `--allow-api-only` to exercise publication plumbing without
creating a publishable runtime.

## Diagnostic experiments

The [OpenCL queue-window experiment](experiments/opencl-queue-window/README.md)
builds a separate arm64 diagnostic AAR for measuring foreground GPU queue
contention. It is not part of the x86 release, is not a supported runtime, and
must not be published under the x86 release workflow.

## License

Repository-authored scripts and documentation use Apache-2.0. Release binaries
are derivative builds of LiteRT and its resolved dependencies. Consult the
license and notice assets included with each release.
