# Downloadable LiteRT runtime experiment

This prerelease repackages the byte-identical native components from
`runtime-v2.1.5-bss.2`. It does not introduce a new LiteRT binary or change the
bounded OpenCL profile.

The release contains:

- a pure API AAR with no `jni/` entries;
- one CPU core bundle for each of `arm64-v8a`, `armeabi-v7a`, `x86_64`, and
  `x86`;
- one arm64 bounded OpenCL GPU bundle containing the accelerator and
  `libBssOcl.so`;
- an immutable component contract, release index, hashes, LiteRT license, and
  third-party notices.

Every CPU ZIP contains only `manifest.json` and `libLiteRt.so`. The arm64 GPU
ZIP requires the exact arm64 core SHA-256 and preserves
`gpu-opencl-bounded-fp32-v1` with kernel batch size 1 and command queue window
size 1.

This release exists only to test loading verified native code from Android
app-private storage. It is not a production update channel. In particular, the
custom pure-x86 runtime retains its historical `LiteRt` SONAME rather than
`libLiteRt.so`; the manifest records that difference explicitly.
