# Complete LiteRT Android runtime and Maven Central roadmap

Status: planned

This roadmap evolves this repository from the existing supplemental Android
`x86` CPU runtime into a complete, source-built LiteRT distribution for
Booming SS. The existing `v2.1.5-bss.1` release remains immutable and retains
its current contract: it only fills the `x86` library missing from Google's
official LiteRT 2.1.5 AAR.

The target Maven coordinate is:

```text
io.github.wluhwluh.bss:litert-android:<upstream>-bss.<revision>
```

The target AAR must be sufficient for Booming SS to consume by itself. It must
not depend on `com.google.ai.edge.litert:litert`, contain model weights, or
require Google Play AI Delivery.

## Release boundary

The complete AAR is deliberately narrower than a full replica of every
upstream LiteRT Android API. It contains the supported API surface and native
runtime needed by Booming SS:

- `classes.jar` with the required `CompiledModel`, `Environment`,
  `TensorBuffer`, accelerator configuration, and related API classes.
- `arm64-v8a`: CPU runtime and GPU accelerator.
- `armeabi-v7a`: CPU runtime.
- `x86_64`: CPU runtime and GPU accelerator.
- `x86`: CPU runtime.
- Android manifest metadata, consumer ProGuard rules, Apache-2.0 license, and
  complete third-party notices.

The artifact excludes unused `ModelProvider` and `AiPackModelProvider` APIs and
must not introduce `com.google.android.play:ai-delivery`. If a complete replica
of the upstream API becomes necessary, it must use a separate artifact rather
than silently expanding this contract.

Shipping an `x86` library in the AAR does not enable source separation on `x86`
in Booming SS. Application support remains controlled by the app's independent
ABI, lifecycle, memory, and device validation gates.

## Non-negotiable requirements

- Every shipped Java, Kotlin, JNI, CPU, and GPU component must be built from
  pinned source in the release workflow.
- No official LiteRT AAR, prebuilt upstream `.so`, binary patch, or diagnostic
  `libOCLQ.so` shim may enter a release artifact.
- The bounded OpenCL queue experiment must be reimplemented as auditable source
  changes with separate kernel-batch and command-queue-window options.
- Queue window `0` must preserve upstream behavior. Queue window `1` is the
  current S10/S25 candidate and remains subject to the final device matrix.
- CPU fallback and a recorded fallback reason remain mandatory, especially on
  S10-class devices.
- Build inputs, toolchains, external archives, generated artifacts, and patches
  must be pinned and checksummed.
- Maven Central artifacts are immutable. A failed or superseded release uses a
  new version.
- This project must not change Booming SS audio window-decoding policy or its
  established MP3 fallback thresholds. Any decoder change requires a separate
  listening-test project.
- Play Store integration is out of scope. The runtime must remain usable by the
  GitHub and F-Droid variants without proprietary Play dependencies.

## Upstream release gate

LiteRT `v2.1.5` cannot be the baseline for a fully source-built release because
its public source cannot rebuild the official `libLiteRtClGlAccelerator.so`.
The latest stable tag, `v2.1.6`, also predates the public GPU accelerator source.

Relevant upstream history:

- GPU accelerator source was published in `3a7cf7f5` on 2026-07-14.
- OSS GPU build fixes landed in
  `876f8a675d1cb15b83214a59073d47390d8dd6aa` on 2026-07-21.

A stable Maven release must wait for the first stable LiteRT tag containing the
required GPU source and build fixes. Phases 2 through 6 may proceed against an
explicitly pinned post-`876f8a675d1c` commit. Such builds are CI or GitHub alpha
artifacts only and must use a commit-identifying version; they must not be named
`2.1.5-bss.1`, `2.1.6-bss.1`, or otherwise imply a stable upstream baseline.

## Current priority

Infrastructure work proceeds now in this order:

| Phase | Work | State |
| --- | --- | --- |
| 1 | Freeze a stable, source-buildable upstream baseline | Waiting on upstream tag |
| 2 | Freeze API, JNI, and ABI contracts | Next |
| 3 | Implement auditable source patches | Queued |
| 4 | Build one complete multi-ABI AAR from source | Queued |
| 5 | Assemble the Maven Central artifact set | Queued |
| 6 | Enforce static checks and reproducibility | Queued |
| 7+ | Device validation, publishing, migration, and F-Droid | After a candidate AAR exists |

Phases 2 through 6 form the current implementation tranche. They should land
as small, independently reviewable commits. Their workflows may publish CI
artifacts, but must not publish a stable Maven Central version before Phase 1
passes.

## Phase 1: Freeze the upstream baseline

Goal: select the first stable upstream source tree that can build both the CPU
runtime and GPU accelerator without proprietary or prebuilt inputs.

- [ ] Confirm that the selected stable tag contains `876f8a675d1c` or an
      equivalent later fix.
- [ ] Build the unmodified upstream CPU and GPU Android targets from a clean
      checkout.
- [ ] Pin LiteRT, `ml_drift`, TensorFlow, Bazel, NDK, JDK, Android SDK, Python,
      `rules_android_ndk`, and every external archive by version and SHA-256.
- [ ] Record the selected tag, full commit IDs, patch base, and upstream
      licenses in a machine-readable lock file.
- [ ] Define the stable `<upstream>-bss.<revision>` version from the selected
      upstream tag.

Exit condition: clean source builds produce the unmodified CPU and GPU runtime
components, and every input is independently fetchable and verified.

## Phase 2: Freeze API, JNI, and ABI contracts

Goal: define exactly what the complete Booming SS runtime promises before
changing native build rules.

- [ ] Scan the pinned Booming SS consumer commit for every LiteRT class,
      constructor, method, enum, and accelerator option it uses.
- [ ] Record the public package names and signatures in a reviewable API
      baseline and add an automated compatibility check.
- [ ] Inventory the JNI exports used by the Java/Kotlin API and the symbols
      required for GPU accelerator discovery.
- [ ] Freeze `minSdk 23`, JVM 17 bytecode, library names, SONAMEs, Android API
      level, and the supported ABI matrix.
- [ ] Record CPU-only and CPU-plus-GPU expectations separately for each ABI.
- [ ] Define the exclusion list for provider APIs and Play AI Delivery.
- [ ] Add a consumer compile fixture proving that Booming SS can compile
      against the repository-built API without package-name changes.
- [ ] Define an API-diff report against the matching official upstream
      `classes.jar`, with intentional exclusions documented.

Deliverables should include a human-readable contract, a machine-readable API
allowlist, JNI symbol allowlists, and a small consumer compilation test.

Exit condition: an API or JNI change fails CI unless the contract is explicitly
updated and reviewed.

## Phase 3: Implement auditable source patches

Goal: replace the current diagnostic binary modifications with a deterministic
source patch series.

- [ ] Preserve the existing Android `x86` CPU toolchain and build-rule support
      as a standalone, documented patch.
- [ ] Add independent `kernelBatchSize` and `commandQueueWindowSize` options to
      the supported Android API.
- [ ] Carry both values through Kotlin/Java, JNI, LiteRT GPU options, and
      `ml_drift` without conflating their meanings.
- [ ] Bound unfinished OpenCL submissions with event waits in the delegate.
- [ ] Prove that queue window `0` is behaviorally equivalent to unmodified
      upstream execution.
- [ ] Preserve GPU initialization and inference fallback to a fresh CPU
      session, including a machine-readable fallback reason.
- [ ] Add unit or host tests for option defaults, propagation, invalid values,
      and fallback diagnostics.
- [ ] Store all changes as ordered textual patches that apply cleanly with a
      fixed direction and fail on fuzz or unexpected offsets.
- [ ] Remove all release-path references to binary patching and `libOCLQ.so`.

The existing `experiments/opencl-queue-window` directory remains diagnostic
evidence only. It must never become a release input.

Exit condition: a clean upstream checkout plus the recorded patch series builds
the modified targets without any binary transformation.

## Phase 4: Build the complete multi-ABI runtime

Goal: produce one deterministic AAR containing the supported API and every
required native library.

- [ ] Build `libLiteRt.so` from source for `arm64-v8a`, `armeabi-v7a`,
      `x86_64`, and `x86`.
- [ ] Build `libLiteRtClGlAccelerator.so` from source for `arm64-v8a` and
      `x86_64`.
- [ ] Compile the public Java/Kotlin API once and package one canonical
      `classes.jar`.
- [ ] Add the manifest, consumer ProGuard rules, licenses, and notices.
- [ ] Assemble a single AAR with deterministic entry order, timestamps,
      permissions, and compression settings.
- [ ] Keep the old x86-only release workflow isolated until the complete
      runtime workflow has replaced it deliberately.
- [ ] Scan source and build input directories before packaging; fail if an
      official AAR or unapproved prebuilt `.so` is present.
- [ ] Upload complete-runtime builds as CI artifacts while Phase 1 remains
      open.

Exit condition: a clean runner creates one AAR with exactly the intended API
and native-library matrix, without consuming the official LiteRT AAR.

## Phase 5: Assemble Maven Central artifacts

Goal: create the complete signed publication payload without publishing it.

The candidate build must generate:

```text
litert-android-<version>.aar
litert-android-<version>-sources.jar
litert-android-<version>-javadoc.jar
litert-android-<version>.pom
Gradle module metadata
```

- [ ] Configure Gradle `maven-publish` and `signing`; use the Vanniktech Maven
      Publish plugin if it reduces custom publication logic.
- [ ] Put the supported Java/Kotlin API sources in `sources.jar`. Publish the
      native source lock, patch series, and rebuild manifest with the GitHub
      Release rather than embedding an entire upstream checkout in that JAR.
- [ ] Generate valid Javadoc or Dokka output for the supported API.
- [ ] Ensure the POM has no dependency on the official LiteRT artifact or Play
      AI Delivery.
- [ ] Generate SHA-256 files, detached OpenPGP signatures, SPDX or CycloneDX
      SBOMs, a build manifest, patch hashes, and complete third-party notices.
- [ ] Make publication metadata suitable for the future
      `io.github.wluhwluh.bss` namespace.
- [ ] Add a local staging repository task so CI can validate the exact Maven
      payload without Central credentials.

Exit condition: the local staging repository can be consumed by the Booming SS
compile fixture and contains every attachment Maven Central requires.

## Phase 6: Enforce static checks and reproducibility

Goal: make provenance, ABI drift, and nondeterminism release blockers.

- [ ] Inspect each ELF for architecture, minimum Android API, SONAME, JNI
      exports, accelerator discovery symbols, and an explicit `NEEDED`
      allowlist.
- [ ] Reject duplicate ABI entries, unexpected vendor libraries, official
      LiteRT transitive dependencies, and provider or Play classes.
- [ ] Scan the complete action inputs and packaging directories for prebuilt
      `.so` files, official AARs, and binary-patch outputs.
- [ ] Validate POM, Gradle metadata, checksums, signatures, SBOMs, source JAR,
      Javadoc JAR, and license attachments.
- [ ] Build twice in independent clean workspaces or runners and compare every
      publication file byte for byte.
- [ ] If native outputs differ, identify and remove embedded paths, timestamps,
      random IDs, nondeterministic archive order, or toolchain drift before the
      phase can pass.
- [ ] Store the comparison report, tool versions, dependency graph, and input
      hashes with the candidate artifact.

Exit condition: two clean builds produce byte-identical AAR and Maven payloads,
and all static policy checks pass.

## Phase 7: Validate the final candidate AAR

All tests must consume the packaged candidate AAR from a local Maven repository,
not loose classes or temporary native libraries.

| Target | Required coverage |
| --- | --- |
| S10 arm32 | CPU |
| S10 arm64 | CPU, GPU, GPU-to-CPU fallback |
| S25 arm64 | CPU, GPU, GPU-to-CPU fallback |
| API 37 x86_64 emulator | CPU and graceful GPU unavailability where applicable |
| API 26 pure x86 emulator | JNI smoke plus internal 9662 and KARA validation |

The matrix covers numerical parity, finite output, cancellation, cache output,
process death, background continuation, low-memory behavior, and fallback
diagnostics. GPU tests also record foreground scrolling FPS, longest frame,
separation duration, PSS, thermal state, and power behavior. Queue windows `0`
and `1` must be compared on S10 and S25. S10 retains CPU fallback even if the
bounded queue improves responsiveness.

Exit condition: the candidate satisfies correctness and lifecycle tests, and
the queue policy has an evidence-backed default for each supported GPU path.

## Phase 8: Configure Maven Central identity and secrets

- [ ] Verify the `io.github.wluhwluh` namespace in Central Portal.
- [ ] Create a dedicated OpenPGP release key and Central user token.
- [ ] Store the token, in-memory private key, and passphrase only in GitHub
      Secrets.
- [ ] Protect the release environment with required human approval.
- [ ] Keep ordinary pull-request workflows read-only and credential-free.

Exit condition: a dry-run staging bundle passes Central validation without
making a public release.

## Phase 9: Publish candidates and stable releases

- [ ] Ordinary pull requests build, test, and upload CI artifacts only.
- [ ] A fixed candidate tag creates the Maven bundle, SBOM, provenance,
      validation report, and GitHub attestations without automatic publication.
- [ ] Device validation is performed against that exact tag and artifact hash.
- [ ] A protected job publishes the same files to Central after manual approval.
- [ ] Central validation completes before the matching GitHub Release is
      created with identical hashes and attachments.
- [ ] Failed releases increment the version; no Central artifact is replaced.

Exit condition: the coordinate resolves from Maven Central and matches the
attested GitHub Release byte for byte.

## Phase 10: Migrate Booming SS

After the Central artifact passes the device matrix, Booming SS switches to the
new coordinate and removes:

- `app/src/main/jniLibs/x86/libLiteRt.so`;
- the official LiteRT dependency;
- local Maven experiment overrides;
- binary OpenCL patching and `libOCLQ.so` paths.

The app build must fail if official LiteRT is reintroduced transitively. APK
inspection must show exactly one expected native library per ABI. Installation
size, runtime PSS, fallback behavior, process isolation, and background
execution are then re-baselined.

Exit condition: Booming SS builds and passes its app-level matrix using only the
Central runtime dependency.

## Phase 11: Verify F-Droid compatibility

- [ ] Run the F-Droid scanner against the release source.
- [ ] Confirm the repository contains no checked-in `.so`, proprietary Play AI
      dependency, or downloaded binary substituted for a source build.
- [ ] Ensure the Maven artifact can be rebuilt from the tagged source,
      checksummed inputs, and documented patch series.
- [ ] Retain complete license, SBOM, provenance, and reproducibility evidence.

Maven Central improves distribution and artifact identity but does not replace
F-Droid's source-rebuild and licensing requirements.

## Phase 12: Maintain the runtime

Stable versions follow `<upstream>-bss.<revision>`. Every upstream upgrade
reapplies and reviews the complete patch series, regenerates licenses and SBOMs,
and reruns the ABI, model, GPU responsiveness, fallback, lifecycle, and
background-execution matrices. Any queue-policy or ABI change requires a new
immutable release.

## Completion criteria

The migration is complete only when:

1. a stable, source-buildable upstream tag is pinned;
2. the complete AAR and Maven payload are reproducible from source;
3. the full device and lifecycle matrix passes against the packaged AAR;
4. Maven Central and GitHub publish identical, signed, attested files;
5. Booming SS no longer consumes the official AAR or local native overrides;
6. the source and dependency graph pass F-Droid-oriented checks.
