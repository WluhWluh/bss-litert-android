# LiteRT 2.1.5 x86 UVR validation

Date: 2026-07-20

The release binary was tested on an API 26 pure x86 Android emulator with 2 GB
RAM. The host CPU was an AMD Ryzen AI 9 HX 370. Tests used static float32
TFLite conversions, eight CPU threads, one warmup, three measured inferences,
and the same first Coast Town MDX window used for the Android first-batch
comparison.

| Model | Median wall | Mean CPU | PSS delta | SNR vs ORT | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| `UVR_MDXNET_3_9662` | 1,334.8 ms | 5,088 ms | 504.5 MiB | 97.60 dB | Pass |
| `UVR_MDXNET_KARA` | 1,335.3 ms | 5,233 ms | 496.4 MiB | 110.73 dB | Pass |
| `UVR-MDX-NET-Inst_HQ_4` | - | - | - | - | Allocation failure |

For 9662 and KARA, output cosine similarity against desktop ONNX Runtime 1.26
was above `0.9999999999`, all values were finite, and tensor shapes matched.
Compared with `tensorflow-lite:2.16.1` on the same emulator, LiteRT was 14.65x
and 15.55x faster respectively.

HQ4 delegated all 183 nodes to XNNPACK but failed while reshaping and
allocating the runtime. Repeating with one CPU thread failed at the same stage.
HQ4 should therefore be treated as unavailable on a 2 GB, 32-bit x86 device.

The Release workflow additionally runs a small ADD model from the pinned
LiteRT source tree on an API 26 pure x86 emulator. Full UVR preset smoke will
move into CI after `bss-tflite` publishes immutable model assets and hashes.
