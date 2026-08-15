# Booming SS LiteRT Android runtime builds

This repository produces unofficial Android LiteRT runtimes used by Booming
SS. It currently maintains two release tracks and one loading experiment:

- an x86-only CPU/JNI supplement for the official LiteRT 2.2.0 AAR pair;
- a GitHub-only multi-ABI AAR whose arm64 GPU path uses the fixed
  `gpu-opencl-bounded-fp32-v1` profile.
- downloadable CPU-core and bounded-GPU component bundles derived byte-for-byte
  from that multi-ABI AAR.

This project is not affiliated with or endorsed by Google or the LiteRT
project. It contains no music source-separation model weights.

## Bounded GPU runtime

`io.github.wluhwluh.bss:litert-android:2.2.0-bss.1` deterministically combines
the official LiteRT implementation/API AAR pair for Booming SS GitHub builds.
Its native matrix is:

- `arm64-v8a`: CPU runtime, JNI bridge, GPU accelerator, and fixed N=1 OpenCL shim;
- `armeabi-v7a`: CPU runtime and JNI bridge;
- `x86_64`: CPU runtime and JNI bridge;
- `x86`: source-built CPU runtime and JNI bridge from `v2.2.0-bss.1`.

The runtime contract is stored in
[`contracts/bounded-gpu-runtime-contract.json`](contracts/bounded-gpu-runtime-contract.json).
Build it on Linux or WSL with:

```bash
./scripts/build-bounded-gpu-runtime.sh
```

Outputs are written to `dist/bounded-gpu-runtime/`. The dedicated workflow
builds the candidate on two clean runners and publishes only byte-identical
outputs from a tag such as `runtime-v2.2.0-bss.1`.

## Downloadable runtime experiment

The experimental component contract is stored in
[`contracts/downloadable-runtime-contract.json`](contracts/downloadable-runtime-contract.json).
Build it with:

```bash
./scripts/build-downloadable-api.sh
python3 scripts/build_downloadable_runtime_bundles.py
python3 scripts/verify_downloadable_runtime_bundles.py \
  --readelf "${ANDROID_NDK_HOME}/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
```

The API build applies a hash-locked patch series to LiteRT 2.2.0 and produces a
classes-only AAR with an explicit split-library loader. The component builder
then verifies the immutable `runtime-v2.2.0-bss.1` source AAR and writes four
ABI-specific CPU ZIPs, the arm64 bounded-GPU ZIP, release index, and checksums
under `dist/downloadable-runtime/`. No native binary is rebuilt or modified by
the component builder.

Each CPU component contains `libLiteRt.so` and `liblitert_jni.so`. Its manifest
freezes their roles, hashes, ELF metadata, and load order. In explicit mode,
`LiteRtNativeLibraryLoader.configureAbsolutePath(String)` receives the runtime
path, derives the sibling JNI path, and loads runtime then JNI. The packaged-AAR
fallback remains `System.loadLibrary("litert_jni")`. The bounded GPU component
requires the exact arm64 runtime and custom JNI identities so it cannot be
combined with an unpatched 2.2 JNI bridge.

## x86 supplement contents

Each release publishes:

- Canonical `libLiteRt-<version>-android-x86.so` and
  `liblitert_jni-<version>-android-x86.so` binaries.
- A native-only convenience AAR containing both x86 libraries.
- SHA-256 checksums and a machine-readable build manifest.
- LiteRT and resolved third-party license files.
- Build logs, GitHub build provenance, and x86 validation reports.

The binary must be paired with the exact official Java/Kotlin API version
recorded in `build-manifest.json`. For `2.2.0-bss.1`, `litert` brings the
matching `litert-api` dependency:

```kotlin
implementation("com.google.ai.edge.litert:litert:2.2.0")
```

For a single Android app, consume the canonical binary directly:

```text
app/src/main/jniLibs/x86/libLiteRt.so
app/src/main/jniLibs/x86/liblitert_jni.so
```

Do not add `pickFirst` for this library. A duplicate x86 runtime after a future
official LiteRT upgrade should fail the build and force an explicit review.

## x86 supplement build

The build is pinned in `config/release.env` and currently uses:

- LiteRT `v2.2.0` at commit
  `145c7523ff08d5e57ab5c582141775eea47da9c7`.
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
git tag v2.2.0-bss.1
git push origin v2.2.0-bss.1
```

The release workflow builds from source, verifies the ELF architecture,
dynamic dependencies, and JNI exports, runs a small model on an API 26 pure x86
emulator, generates provenance, and publishes the resulting assets.

The v2.2 release does not inherit the old v2.1.5 UVR evidence. Its current x86
contract is the API 26 pure-x86 inference test documented in
`docs/x86-validation-2.2.0-bss.1.md`.

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

## Release policy checks

Every complete-runtime build now records and enforces:

- the exact ELF ABI, Android API, SONAME, `DT_NEEDED`, JNI, and accelerator
  symbol contracts;
- Bazel action graphs that do not consume `litert/prebuilt` libraries;
- textual source patches and Git LFS-only upstream binary placeholders;
- component, AAR, POM, Gradle metadata, SBOM, checksum, OpenPGP signature, and
  license consistency;
- a sorted target dependency graph, locked tool versions, input hashes, and
  repository/source commits.

The manual complete-runtime workflow builds and stages the candidate twice in
independent workspaces, compares all deterministic files, verifies a second
staging tree signed with an ephemeral test key, and creates a deterministic
Maven Central upload bundle. OpenPGP signatures are verified but excluded from
byte comparison because their creation time is intentionally nondeterministic.

## Diagnostic experiments

The [OpenCL queue-window experiment](experiments/opencl-queue-window/README.md)
builds a separate arm64 diagnostic AAR for measuring foreground GPU queue
contention. It is not part of the x86 release, is not a supported runtime, and
must not be published under the x86 release workflow.

## License

Repository-authored scripts and documentation use Apache-2.0. Release binaries
are derivative builds of LiteRT and its resolved dependencies. Consult the
license and notice assets included with each release.
