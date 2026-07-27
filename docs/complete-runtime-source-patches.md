# Complete runtime source patches

The ordered patch set in `patches/complete-runtime` is the only supported
source modification path for the complete runtime. It targets LiteRT commit
`876f8a675d1cb15b83214a59073d47390d8dd6aa` and is locked by SHA-256 in
`config/complete-runtime-source-lock.json`.

## Patch order

1. `0001-android-x86-build-fixes.patch` preserves the two source dependency
   corrections already validated by the supplemental x86 release. The pinned
   LiteRT tree already registers a newer Android NDK toolchain, so this patch
   deliberately does not carry the old `rules_android_ndk` override.
2. `0002-gpu-options-api.patch` adds independent `kernelBatchSize` and
   `commandQueueWindowSize` values from Kotlin through JNI, C/C++ GPU options,
   TOML serialization, and ML Drift delegate options.
3. `0003-bounded-opencl-queue.patch` waits on an OpenCL boundary event after
   the configured number of submitted kernel batches.
4. `0004-core-kotlin-api.patch` adds a pure Booming SS API target and minimal
   manifest without model providers, copied TensorFlow Lite Interpreter
   classes, Play AI Delivery, or an ABI-specific JNI dependency.

`commandQueueWindowSize` accepts values from 0 through 1024. Zero is the
default and executes the existing dispatch path without creating an event or
waiting. A positive value takes effect only when `kernelBatchSize` is also
positive. The current device-test candidate remains batch size 1 and queue
window 1; neither value is a stable default until the final S10/S25 matrix is
complete.

GPU initialization and fallback remain a Booming SS consumer responsibility.
The application already destroys a failed GPU session, creates a fresh CPU
session, and records the failure stage. This runtime patch must not hide a GPU
failure or reuse a partially initialized GPU session.

## Application

The patch command requires an exact, clean Git worktree and never auto-reverses
patches:

```bash
python3 scripts/apply-complete-runtime-patches.py \
  --source /path/to/litert
```

Use `--verify-only` to check the base commit, patch hashes, series order, and
clean application without modifying the checkout. Any Git diagnostic
containing an offset or fuzz is rejected.

## Upstream source blocker

The pinned LiteRT commit declares `@ml_drift` as an `http_archive` with
`strip_prefix = "ml-drift-main"` but supplies no URL or SHA-256. No public
Google ML Drift repository is available at this baseline, and the current
LiteRT main branch retains the same incomplete declaration. Consequently,
the source patch can be audited and its LiteRT-side tests can be prepared, but
the GPU accelerator cannot qualify as a source-built release artifact yet.

The build must fail unless a future stable LiteRT release supplies a publicly
fetchable, checksummed ML Drift source. An unpinned local override, the official
prebuilt accelerator, binary patching, and `libOCLQ.so` are not acceptable
release substitutions.
