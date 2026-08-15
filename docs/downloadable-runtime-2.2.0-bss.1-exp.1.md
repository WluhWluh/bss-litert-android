# Downloadable LiteRT runtime 2.2.0-bss.1-exp.1

This prerelease ports the explicit-path downloadable runtime architecture to
LiteRT 2.2.0. Its native inputs are extracted byte-for-byte from the published
`runtime-v2.2.0-bss.1` combined AAR; the existing combined runtime release is
not replaced or modified.

## Split loader contract

LiteRT 2.2 uses a split native runtime. Every CPU ZIP therefore contains:

- `libLiteRt.so` with role `runtime`;
- `liblitert_jni.so` with role `jni`;
- `manifest.json` with component schema 2, both hashes, exact ELF metadata,
  runtime load evidence, and `loadOrder`.

`com.google.ai.edge.litert.LiteRtNativeLibraryLoader` retains the Booming SS
`configureAbsolutePath(String)` entry point. The configured path must name
`libLiteRt.so`; the loader derives `liblitert_jni.so` from the same directory
and calls `System.load` first for runtime and then for JNI. When no absolute
path is configured, it follows the official 2.2 behavior by calling only
`System.loadLibrary("litert_jni")`.

`Environment`, `CompiledModel`, and `TensorBuffer` all route initialization
through this loader. Reconfiguration to another runtime after configuration or
loading is rejected. The API AAR contains no native entries, model providers,
Play AI Delivery adapters, copied TensorFlow Lite API, foreground-service
permissions, or NPU feature declarations.

## Native identity

The CPU components cover `arm64-v8a`, `armeabi-v7a`, `x86_64`, and `x86`.
Their manifests preserve the upstream SONAME differences, including
`litert_jni` for arm64 and x86 JNI, `liblitert_jni.so` for arm32 and x86_64
JNI, and `LiteRt` for the x86 runtime. JNI records `libLiteRt.so` as a runtime
load rather than a fabricated `DT_NEEDED` dependency.

The arm64 bounded GPU component retains the validated
`gpu-opencl-bounded-fp32-v1` profile with kernel batch size 1 and command queue
window size 1. It requires both exact arm64 CPU identities:

- runtime SHA-256
  `97355a36cb8ac7628cf407773291e98da79f3ef184cc43cb0e57dedf5f0c0637`;
- custom JNI SHA-256
  `708b7a2bcdef55b698878ae237971fbd31d9a6bfcfe6ac81dc62c880ad6b4e8a`.

This prevents the GPU component from being admitted with the official arm64
JNI that lacks the Booming SS kernel-batch mapping.

## Source and reproducibility

The API is built from LiteRT tag `v2.2.0`, commit
`145c7523ff08d5e57ab5c582141775eea47da9c7`. The exact source patch series,
Bazel, Android SDK, NDK, source commit, classes JAR, base AAR, routed classes,
forbidden class prefixes, packaging Python 3.12.3, and zlib 1.3 are frozen in
`downloadable-api-source-lock.json`.

The release workflow:

1. applies the source patches with zero offset and no fuzz;
2. rejects target AAR or shared-library inputs to the classes-only API target;
3. verifies loader methods, bytecode routing, fallback, and the two explicit
   loads;
4. verifies all component SHA-256 identities plus ELF class, machine, SONAME,
   `DT_NEEDED`, runtime load strings, and 16 KiB LOAD alignment;
5. builds on two independent runners and requires byte-identical release
   directories before a prerelease can be published.

## Assets

The candidate contains the classes-only loader AAR, four split CPU components,
one arm64 bounded GPU component, the v3 downloadable contract, v2 release
index, API source lock, checksums, LiteRT license, and third-party notices. It
contains no model weights and remains a GitHub-only experimental channel.

The locally reproduced pinned-Linux candidate identities are:

- API AAR: `a08ce2e2db55c15679adcd81ad83d90f8e907aa271fa80db6a74513aca1ff1e3`;
- arm64 CPU ZIP: `2ef97a9eb6bdbcd86c213f6a4144baef919a756dc54c628d5ed00b9cf451153c`;
- arm32 CPU ZIP: `38ebd334065e6e139c8bc19ceded9553503f3b8dbd05bfaaf615a83adb87a045`;
- x86_64 CPU ZIP: `30a63e2eaa3c5acf1c83eeda9c5931849c28750f6aadb8512edbdf574b890661`;
- x86 CPU ZIP: `a2ce899610d67914b62c2f20db6d6cef5d282d5607845ac51ec5231aba524b56`;
- arm64 bounded GPU ZIP:
  `8a3f743e6ea4c6bc4739b5927e6d3b711a87e57be4bc06077aee5e8f19e621b8`.

These identities were reproduced from two independent source compilations and
two release assembly directories using the pinned Python/zlib environment.
They are local candidate evidence, not a statement that the GitHub prerelease
has been published.

## Remaining device gate

The existing LiteRT 2.2 combined AAR has passed API 26 x86 inference, but that
does not prove the new app-private downloadable path. Before publication or
product rollout, Booming SS must install the v3 x86 CPU ZIP into app-private
storage, configure its runtime path, observe runtime-then-JNI loading, and run
an inference on the API 26 x86 AVD. Equivalent arm32 and arm64 CPU loading must
then be exercised on the S10; bounded GPU remains an arm64-only follow-on gate.
