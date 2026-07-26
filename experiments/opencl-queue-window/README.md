# OpenCL queue-window experiment

This experiment tests whether bounding outstanding OpenCL kernel work improves
Android UI responsiveness during LiteRT GPU inference.

LiteRT 2.1.5 has a native `kernel_batch_size` option, but its Kotlin API and JNI
bridge do not expose it. The experimental runtime redirects Kotlin's otherwise
unused `numStepsOfCommandBufferPreparations` setter to the kernel-batch field.
The binary patch rewrites two arm64 store instructions (8 instruction bytes;
4 file bytes differ) inside one exactly matched 28-byte setter. It is guarded
by the official runtime SHA-256 plus that exact old-setter match.

LiteRT 2.1.5 also ships `libLiteRtClGlAccelerator.so` as a prebuilt binary. Its
OpenCL wrapper dynamically opens `libOpenCL.so`, so the experiment changes that
single loader string to `libOCLQ.so`. The replacement library depends on the
device's original `libOpenCL.so`, forwards other OpenCL entry points through
that dependency, and interposes `clEnqueueNDRangeKernel`.

The same queue-window value configures LiteRT's kernel batch size. This makes
the delegate submit the graph as ordinary NDRange kernels in batches instead
of one command buffer. After every configured number of successful kernel
enqueues on one command queue, the shim requests an event for the boundary
kernel and waits for it. An in-order queue therefore has a bounded amount of
kernel work ahead of Android's graphics workload. Booming SS enables event
waits only around `CompiledModel.run()`, so delegate compilation and autotuning
remain untouched. This follows the queue-window principle used by MACE while
leaving the model graph, kernels, tensor path, and vendor driver unchanged.

The direct reference is MACE's
[`WaitForQueueExecution`](https://github.com/XiaoMi/mace/blob/0fc55a548ef41b37fd15fd8944de5155eb09b3c1/mace/runtimes/opencl/core/opencl_helper.cc),
which documents poor UI responsiveness when too many commands accumulate and
waits on the boundary event after a configured command count. This prototype
uses the same event-boundary idea; the LiteRT patch is additionally necessary
because LiteRT otherwise encapsulates this graph in an OpenCL command buffer.

This is a diagnostic prototype, not a release runtime. It relies on Android's
dynamic-linker lookup of symbols in a library dependency and currently counts
NDRange kernels rather than every possible OpenCL command.

## Build

The build requires Linux or WSL and Android NDK r25b. It verifies the official
LiteRT 2.1.5 AAR and accelerator hashes before modifying anything.

```bash
export ANDROID_NDK_HOME=/opt/android-sdk/ndk/25.1.8937393
./experiments/opencl-queue-window/build.sh
```

Set `OFFICIAL_LITERT_AAR` to use an already downloaded official AAR. Otherwise
the script downloads the pinned artifact from Google's Maven repository.

Outputs are written below `dist/opencl-queue-window/`, including a standalone
local Maven repository at `m2/`. The experimental coordinate is:

```text
com.google.ai.edge.litert:litert:2.1.5-bss.oclq4
```

The repack step normalizes every AAR entry to the ZIP epoch so identical
inputs produce an identical archive SHA-256.

## Runtime control

Set the queue window before starting the app process:

```bash
adb shell setprop debug.bss.opencl_queue_window 8
adb shell am force-stop com.wluhwluh.booming.sourcesep.debug
```

Values from 1 through 1024 enable event waits. `0`, an absent property, or an
invalid value selects pass-through mode. Restart the process after changing the
property because the shim reads it once when loaded.

The AAR is arm64-only for this experiment. Booming SS also checks that the
current process reports `aarch64` before loading the shim; other ABI builds
retain their unmodified LiteRT libraries and leave the experiment disabled.

The Booming SS build must select the local Maven repository and enable its
debug-only Gradle gate:

```bash
./gradlew assembleGithubDebug \
  -PboomingSs.litertExperimentRepository=<repo>/dist/opencl-queue-window/m2 \
  -PboomingSs.litertExperimentVersion=2.1.5-bss.oclq4 \
  -PboomingSs.litertOpenClQueueExperiment=true
```

The gate is forced off for release and CI variants even if these properties
are supplied.

Always include pass-through mode as an experimental-AAR control. It separates
the effect of queue bounding from binary patching and one extra function-call
layer.
