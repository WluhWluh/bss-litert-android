# LiteRT 2.2.0-bss.1 bounded GPU runtime

This GitHub release freezes the Booming SS bounded OpenCL profile as
`gpu-opencl-bounded-fp32-v1` on LiteRT 2.2.0:

- FP32 OpenCL execution on `arm64-v8a`;
- LiteRT `kernel_batch_size=1`;
- one event wait after every submitted OpenCL NDRange kernel while inference is
  active;
- no foreground/background or screen-state policy changes;
- CPU-only LiteRT on `armeabi-v7a`, `x86_64`, and `x86`.

LiteRT 2.2.0 splits its Android implementation and API across the official
`litert` and `litert-api` AARs. This artifact deterministically combines both
hash-pinned inputs so every API class and native library appears exactly once.
It also includes the source-built `v2.2.0-bss.1` x86 runtime/JNI pair.

The arm64 JNI bridge is rebuilt from upstream tag `v2.2.0`, commit
`145c7523ff08d5e57ab5c582141775eea47da9c7`, with a one-line option mapping:
the existing Kotlin `numStepsOfCommandBufferPreparations` field selects the
official LiteRT `kernel_batch_size` option. No ARM64 `libLiteRt.so` machine-code
rewrite is used in this release. The official accelerator remains hash-gated
and receives an equal-length OpenCL loader redirect to `libBssOcl.so`.

The stable `io.github.wluhwluh.bss.litert.BssLiteRtRuntime` API reports both
the Java and native capability identity. Consumers must compare schema,
artifact version, profile ID, kernel batch size, and queue-window size before
creating a GPU session. A missing or mismatched capability must select CPU.

The release contains the combined AAR, deterministic local-Maven bundle,
runtime contract, build manifest, licenses, checksums, and GitHub provenance.
Two clean runners must produce byte-identical outputs. All packaged ARM64 ELF
LOAD segments are required to have at least 16 KiB alignment.

Post-publication ARM64 behavioral evidence, including matching positive
dispatch/event-wait counts and ORT numerical parity, is recorded in
`bounded-gpu-runtime-2.2.0-bss.1-device-validation.md`.
