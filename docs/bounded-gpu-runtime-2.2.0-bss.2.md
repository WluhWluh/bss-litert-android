# LiteRT 2.2.0-bss.2 bounded GPU runtime

This GitHub release freezes the Booming SS bounded OpenCL profile as
`gpu-opencl-bounded-fp32-v1` on LiteRT 2.2.0:

- FP32 OpenCL execution on `arm64-v8a`;
- LiteRT `kernel_batch_size=1`;
- one event wait after every submitted OpenCL NDRange kernel while inference is
  active;
- no foreground/background or screen-state policy changes;
- CPU-only LiteRT on `armeabi-v7a`, `x86_64`, and `x86`.

The ARM64 bounded implementation is unchanged from `2.2.0-bss.1`. This new
immutable identity incorporates the corrected `v2.2.0-bss.2` x86 core/JNI
supplement. Its x86 SONAMEs are `libLiteRt.so` and `liblitert_jni.so`, both ELF
files declare Android API 26, and the upstream API 26 emulator inference gate
includes app-private absolute-path loading.

LiteRT 2.2.0 splits its Android implementation and API across the official
`litert` and `litert-api` AARs. This artifact deterministically combines both
hash-pinned inputs with the hash-pinned x86 supplement so every API class and
native library appears exactly once. The verifier checks both x86 SONAMEs,
Android API notes, and 16 KiB LOAD alignment in the final combined AAR.

The arm64 JNI bridge is rebuilt from upstream tag `v2.2.0`, commit
`145c7523ff08d5e57ab5c582141775eea47da9c7`, with a one-line option mapping:
the existing Kotlin `numStepsOfCommandBufferPreparations` field selects the
official LiteRT `kernel_batch_size` option. No ARM64 `libLiteRt.so` machine-code
rewrite is used. The official accelerator remains hash-gated and receives an
equal-length OpenCL loader redirect to `libBssOcl.so`.

The stable `io.github.wluhwluh.bss.litert.BssLiteRtRuntime` API reports both
the Java and native capability identity. Consumers must compare schema,
artifact version, profile ID, kernel batch size, and queue-window size before
creating a GPU session. A missing or mismatched capability must select CPU.

The release contains the combined AAR, deterministic local-Maven bundle,
runtime contract, build manifest, licenses, checksums, and GitHub provenance.
Two clean runners must produce byte-identical outputs. Before the release tag
is created, the exact candidate AAR must also pass ARM64 capability, two-cold-run
`dispatch == wait > 0`, repeatability, and ORT numerical-parity validation.
