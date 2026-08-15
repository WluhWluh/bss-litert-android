# Third-party notices

The release binaries in this package are unofficial supplemental Android x86
builds of Google LiteRT. They are built from LiteRT `2.2.0`, commit
`145c7523ff08d5e57ab5c582141775eea47da9c7`, plus the hash-locked SONAME patch
published with the release.

LiteRT is licensed under the Apache License 2.0. The build statically links
components fetched by LiteRT's Bazel dependency graph, including TensorFlow
Lite and XNNPACK. Each release includes:

- `LICENSE-LiteRT.txt`, copied from the pinned LiteRT source tree.
- `THIRD_PARTY_LICENSES.txt`, generated from license and notice files in the
  resolved Bazel external repositories.
- `build-manifest.json`, recording the source patch and toolchain versions.

Model weights are not part of this repository or its releases. This project is
not affiliated with or endorsed by Google, the LiteRT project, UVR, or the
authors of any source-separation model.
