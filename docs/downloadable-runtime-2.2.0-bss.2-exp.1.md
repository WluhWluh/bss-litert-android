# Downloadable LiteRT runtime 2.2.0-bss.2-exp.1

This prerelease rebuilds the explicit-path downloadable runtime from the
published `runtime-v2.2.0-bss.2` combined AAR. It supersedes the experimental
`2.2.0-bss.1-exp.1` candidate and does not modify the combined runtime release.

## Corrected split runtime

Every CPU ZIP contains `libLiteRt.so`, `liblitert_jni.so`, and a component
schema 2 manifest. The manifest freezes both hashes, roles, load order, ELF
metadata, runtime-load evidence, and 16 KiB LOAD alignment.

The x86 pair now comes from `v2.2.0-bss.2`. Its SONAMEs match the filenames:

- runtime: `libLiteRt.so`;
- JNI: `liblitert_jni.so`.

This is required for app-private loading because the JNI bridge opens
`libLiteRt.so` after the application has loaded the core by absolute path. The
old x86 `LiteRt` SONAME could not prove that contract. The corrected pair has
already passed API 26 packaged and app-private absolute-path inference in its
source release.

The arm64, armeabi-v7a, and x86_64 CPU libraries are byte-identical to the
previous 2.2 candidate. The arm64 bounded GPU component uses the validated
`2.2.0-bss.2` capability identity while retaining FP32 OpenCL, kernel batch 1,
and command queue window 1. Its exact combined AAR passed two cold S10 runs
with `508 dispatch == 508 wait` and element-wise ORT parity.

## Loader contract

`com.google.ai.edge.litert.LiteRtNativeLibraryLoader` accepts the absolute path
to `libLiteRt.so`, derives `liblitert_jni.so` from the same directory, and loads
core then JNI. `Environment`, `CompiledModel`, and `TensorBuffer` all route
initialization through this loader. Reconfiguration after configuration or
loading is rejected.

When no absolute path is configured, the classes-only API AAR retains the
official LiteRT 2.2 fallback `System.loadLibrary("litert_jni")`. The AAR has no
native libraries, model providers, Play AI Delivery adapters, TensorFlow Lite
API copy, foreground-service permissions, or NPU feature declarations.

The loader source code is unchanged from the prior 2.2 experiment. This
release gives it a new immutable AAR filename and embeds the bss.2 runtime
contract plus its updated source lock.

## Source and reproducibility

The native source AAR is `litert-android-2.2.0-bss.2.aar`, 13,102,718 bytes,
SHA-256 `35b55a0ef9a6d28e56271a9bc3b6b6cc8a84b16732b17b34b2a6b51ee7be3124`.
The API is built from LiteRT tag `v2.2.0`, commit
`145c7523ff08d5e57ab5c582141775eea47da9c7`.

The release workflow builds on two independent Ubuntu 24.04 runners, requires
byte-identical directories, verifies every contract/hash/ELF/load-order rule,
checks the classes-only API bytecode, and publishes only from the matching
`downloadable-runtime-v2.2.0-bss.2-exp.1` tag.

## Assets

The candidate contains:

- `litert-api-2.2.0-bss.2-downloadable-loader.aar`;
- one CPU ZIP for each of arm64-v8a, armeabi-v7a, x86_64, and x86;
- one arm64-v8a bounded GPU ZIP;
- the v3 runtime contract, v2 release index, API source lock, checksums,
  license, and third-party notice.

It contains no model weights and remains a GitHub-only experimental channel.

## Product gate

Before the release tag is created, the exact clean-runner candidate must be
installed through Booming SS's normal Runtime Management/download store. The
gate must cover CPU loading and real MDX inference on S10 arm64 and forced
armeabi-v7a plus the existing x86 and x86_64 AVDs. The arm64 S10 row must also
exercise the downloaded bounded GPU component and verify its full capability
identity and positive equal dispatch/wait counts. NPU paths are out of scope.
