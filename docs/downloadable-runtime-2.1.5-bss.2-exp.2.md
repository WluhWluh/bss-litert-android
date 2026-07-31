# Downloadable LiteRT runtime 2.1.5-bss.2-exp.2

This prerelease replaces the `exp.1` API AAR with a source-built classes-only
API that supports explicit absolute-path native loading. The CPU and bounded
GPU native payloads remain byte-identical to `runtime-v2.1.5-bss.2`.

## Loader contract

`com.google.ai.edge.litert.LiteRtNativeLibraryLoader` provides:

- `configureAbsolutePath(String)` to select one canonical native library;
- `load()` for thread-safe, idempotent initialization;
- `isLoaded()` and `configuredAbsolutePath()` diagnostics.

`Environment`, `CompiledModel`, and `TensorBuffer` all route their static
initialization through this loader. A consumer must verify and install the
native component, configure its absolute path, and load it before first use of
any other LiteRT API class. Reconfiguring to a different path is rejected.
Without explicit configuration the loader retains packaged-AAR compatibility
by calling `System.loadLibrary("LiteRt")`.

This change addresses Android 8 behavior where an earlier `System.load()` from
application code succeeds but a later API-class `System.loadLibrary()` still
fails because the APK native search path contains no `libLiteRt.so`.

## Source and reproducibility

The API is built from LiteRT 2.1.5 commit
`9d26e89d88ef8785b6a1e54ec41ac8add215a125`. The exact patch series, Bazel,
Android SDK, NDK, source commit, output hashes, routed classes, and forbidden
class prefixes are frozen in `downloadable-api-source-lock.json`.

Each release runner:

1. Applies both patches with zero offset and no fuzz.
2. Builds only the core Kotlin API target, without JNI or model-provider code.
3. Rejects any AAR or shared-library input in that target's Bazel action graph.
4. Verifies JVM bytecode, public loader methods, all three routed static
   initializers, packaged-library fallback, and the absence of native entries.
5. Verifies the original multi-ABI AAR before extracting native components.
6. Produces deterministic archives and checksums.

Two independent GitHub runners must produce byte-identical final release
directories before publication.

## Assets

The prerelease contains:

- `litert-api-2.1.5-bss.2-downloadable-loader.aar`;
- one CPU core ZIP for each of `arm64-v8a`, `armeabi-v7a`, `x86_64`, and `x86`;
- the arm64 bounded OpenCL GPU component;
- the downloadable runtime contract and API source lock;
- release index, checksums, LiteRT license, and third-party notices.

This remains an experimental GitHub-only component channel. It contains no
model weights and is not a Maven Central release.
