# Complete runtime contract

This document is the human-readable companion to
`contracts/complete-runtime-contract.json`. The JSON file is authoritative for
automated checks.

## Consumer baseline

The contract is derived from Booming SS commit
`05c1d6b6e28ee666e488e38d43340f600fd04a6f`. It preserves the package names and
LiteRT 2.1.5 API used by the application. The consumer fixture uses Kotlin
2.3.21 and emits JVM 17 bytecode, matching that application baseline. The BSS
runtime adds two independent GPU controls:

- `kernelBatchSize` controls delegate kernel batching;
- `commandQueueWindowSize` limits unfinished OpenCL command submissions.

The two values must remain separate throughout Kotlin, JNI, LiteRT options, and
ML Drift. A queue window of `0` preserves upstream behavior.

## Native ABI matrix

The post-2.1.6 source layout separates the public API JNI bridge from the
runtime implementation. The complete AAR therefore contains:

| Library | arm64-v8a | armeabi-v7a | x86_64 | x86 |
| --- | --- | --- | --- | --- |
| `liblitert_jni.so` | yes | yes | yes | yes |
| `libLiteRt.so` | yes | yes | yes | yes |
| `libLiteRtClGlAccelerator.so` | yes | no | yes | no |

`liblitert_jni.so` exports the JNI methods used by `Environment`,
`CompiledModel`, and `TensorBuffer`. `libLiteRt.so` supplies the runtime C API.
The GPU accelerator exports `LiteRtAcceleratorImpl` and is discovered only on
the two GPU-capable packaged ABIs.

Including the x86 libraries does not declare x86 source separation supported in
Booming SS. The application retains its own memory and lifecycle gate.

## API boundary

The AAR packages the core API required by Booming SS. It excludes:

- `ModelProvider`;
- `AiPackModelProvider`;
- copied TensorFlow Lite Interpreter APIs;
- Google Play AI Delivery and its coroutine adapters.

The generated POM must not depend on the official LiteRT artifact or Play AI
Delivery. Kotlin standard-library metadata may be declared when required by the
compiled API.

## Compatibility checks

`scripts/verify-runtime-contract.py` has two modes:

- `reference` verifies the established API against the pinned official LiteRT
  2.1.5 AAR without treating that AAR as a release input;
- `complete` additionally requires the BSS GPU extensions, the exact native ABI
  matrix, and absence of forbidden classes.

The Kotlin consumer fixture in `smoke/contract` compiles the same operations used
by Booming SS. It defaults to the official reference and accepts
`-PlitertContractAar=<path>` to compile against a locally built candidate.
