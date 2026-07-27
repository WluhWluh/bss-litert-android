# LiteRT 2.1.5-bss.2 bounded GPU runtime

This GitHub-only runtime freezes the bounded OpenCL profile validated by
Booming SS as `gpu-opencl-bounded-fp32-v1`:

- FP32 OpenCL execution on `arm64-v8a`;
- LiteRT `kernel_batch_size=1`;
- one event wait after every submitted OpenCL NDRange kernel while inference is
  active;
- no foreground/background or screen-state policy changes;
- CPU-only LiteRT on `armeabi-v7a`, `x86_64`, and `x86`.

The AAR is built from the hash-pinned official LiteRT 2.1.5 AAR. The arm64
runtime redirects the otherwise unused
`numStepsOfCommandBufferPreparations` API field to LiteRT's internal kernel
batch option. The arm64 accelerator loads `libBssOcl.so`, which forwards to
the device OpenCL library and applies the fixed event-wait boundary. The x86
runtime is the immutable `v2.1.5-bss.1` source build from this repository.

The stable `io.github.wluhwluh.bss.litert.BssLiteRtRuntime` API reports both
the Java and native capability identity. Consumers must compare schema,
artifact version, profile ID, kernel batch size, and queue-window size before
creating a GPU session. A missing or mismatched capability must select CPU.

This artifact intentionally reuses two tightly hash-gated binary transforms
from the successful diagnostic experiment. It is intended for Booming SS
GitHub builds and is not represented as a complete public-source LiteRT GPU
build or an F-Droid-compatible artifact.

The release contains the AAR, a deterministic local-Maven bundle, the exact
runtime contract, component/build manifest, licenses, checksums, and GitHub
build provenance. Two clean GitHub runners must produce byte-identical release
files before publication.
