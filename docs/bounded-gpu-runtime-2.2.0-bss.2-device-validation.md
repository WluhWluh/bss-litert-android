# LiteRT 2.2.0-bss.2 ARM64 device validation

This report records pre-publication behavioral validation of the exact AAR
from clean-runner candidate workflow run `31873212576`. The validation was run
on 2026-08-15 in the America/Los_Angeles time zone.

## Frozen identities

- Runtime AAR: `litert-android-2.2.0-bss.2.aar`, 13,102,718 bytes,
  SHA-256 `35b55a0ef9a6d28e56271a9bc3b6b6cc8a84b16732b17b34b2a6b51ee7be3124`.
- Candidate source commit:
  `a190826ae1d27dfc036fd113b04f529fb935e214`.
- Validation APK: 66,396,189 bytes,
  SHA-256 `c1c13ab24c458fcb9fa32185321b012ef7625106ea33db85f3d5249c75f22127`.
- Benchmark base revision:
  `90fa4ef82e6f5264d562b4a470608b2b401812ed`.
- Device: Samsung SM-G9730, Qualcomm SM8150, Adreno 640, Android 12 / API 31,
  64-bit `arm64-v8a` process.

The validation APK used an isolated dirty test worktree. Its only runtime
adapter changes set the expected artifact to `2.2.0-bss.2`, report LiteRT
`2.2.0`, and omit the historical standalone 2.1.5 x86 supplement when the
combined local AAR is supplied. The APK and runtime hashes above freeze the
actual executable inputs despite that test-only source state.

The model contract was `uvr_mdxnet_3_9662@2`. Its frozen inputs were:

- contract SHA-256
  `edf02de52bb45c842ad65a4be8f2118ed6d212ec4590a81ae0401e760bfb4fe9`;
- ONNX SHA-256
  `e02220e80d8253f4c2209f8924298b2b686bbdf2868b788ff5500fb9bd94aadc`;
- LiteRT model SHA-256
  `f74eee1ac06845a7cf277416138b19a6203f34316a3a74b2bde19acbfb2f8378`;
- NCHW FP32 input SHA-256
  `1ce5225c5d248c6c1bbdcc2ef270741ef37c9c7e873bc19c58bd5decef7b534a`.

## Device results

Every run used one warmup and three measured inferences. The runner force-
stopped the app before every invocation, so the two GPU rows are independent
cold app processes. All 2,097,152 output elements were finite and the device
thermal status remained zero.

| Backend | Median wall time | Dispatches | Event waits | Output SHA-256 |
| --- | ---: | ---: | ---: | --- |
| ORT CPU | 3225.30 ms | n/a | n/a | `ca1829e06b343897ebbff1ad303b7d3ee773fa8165476b0f4ce1c338f3721248` |
| LiteRT CPU | 3035.37 ms | n/a | n/a | `7e0a67f0092ec3a37f0c724313790f48d959078aa47c672bd875b648e8e69729` |
| Bounded GPU cold run 1 | 2312.16 ms | 508 | 508 | `153e564410bdf02b952605419c435e5598d0d40896fdd5b0da45af903d7b4d5f` |
| Bounded GPU cold run 2 | 2392.48 ms | 508 | 508 | `153e564410bdf02b952605419c435e5598d0d40896fdd5b0da45af903d7b4d5f` |

Both GPU runs reported capability schema 1, artifact `2.2.0-bss.2`, profile
`gpu-opencl-bounded-fp32-v1`, `kernelBatchSize=1`, and
`commandQueueWindowSize=1`. The identical GPU output hashes establish
repeatability. The matching positive dispatch and event-wait counts establish
one wait per submitted OpenCL kernel while inference was marked active.

## Numerical comparison

The four exported 8,388,608-byte FP32 tensors were compared independently on
the host. Every comparison passed element-wise `atol=1e-4, rtol=1e-4`.

| Pair | Maximum absolute error | Mean absolute error | RMSE | SNR | Cosine similarity |
| --- | ---: | ---: | ---: | ---: | ---: |
| LiteRT CPU vs ORT | 3.76105e-5 | 1.46469e-6 | 2.59058e-6 | 103.2063 dB | 0.999999999976 |
| Bounded GPU vs ORT | 4.49419e-5 | 1.32132e-6 | 2.37862e-6 | 103.9477 dB | 0.999999999980 |
| Bounded GPU vs LiteRT CPU | 4.21703e-5 | 1.60211e-6 | 2.84930e-6 | 102.3795 dB | 0.999999999971 |

The accompanying raw-report archive is
`litert-2.2.0-bss.2-s10-arm64-validation.zip`, 9,322 bytes, SHA-256
`6a4dbdd7285dde382af767850081e84e95e0490e6c9eb76d13cdefc2c53f4d0b`.
It contains the four device-generated JSON reports used above.

## Scope

This closes the exact-candidate ARM64 capability, dispatch/wait,
repeatability, and numerical-parity gates for one Qualcomm SM8150 device and
the frozen MDX 9662 tensor window. It does not claim full-song, lifecycle,
MediaTek GPU, FP16, or NPU validation.
