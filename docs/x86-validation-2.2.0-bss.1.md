# LiteRT 2.2.0-bss.1 x86 validation

The release workflow builds `libLiteRt.so` and `liblitert_jni.so` from LiteRT
tag `v2.2.0`, commit `145c7523ff08d5e57ab5c582141775eea47da9c7`.

Before publication, it verifies that both files are 32-bit Intel Android ELF
shared libraries, contain the expected split runtime/JNI symbol sets, and have
no EGL, GLES, OpenCL, Vulkan, or unexpected dynamic dependencies.

The workflow then installs the package on an API 26 pure-x86 emulator and runs
the upstream dynamic-shape add model through the public LiteRT Kotlin API. The
test requires CPU discovery, successful compilation and execution, finite
outputs, and element-wise numerical agreement at `1e-5` tolerance.

This release does not reuse the LiteRT 2.1.5 UVR result. Full source-separation
presets remain outside the supported 32-bit x86 contract until separately
revalidated against this exact pair of binaries.
