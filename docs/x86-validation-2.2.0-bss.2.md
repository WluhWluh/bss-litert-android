# LiteRT 2.2.0-bss.2 x86 validation

The release workflow builds `libLiteRt.so` and `liblitert_jni.so` from LiteRT
tag `v2.2.0`, commit `145c7523ff08d5e57ab5c582141775eea47da9c7`, plus the
hash-locked x86 SONAME normalization patch.

The patch SHA-256 is
`986ab875563140cbc20ccc40a62e09cc8d984b640bdb0f87e11bb2680e5188e8`.
Both ELF files must declare Android API 26 in `.note.android.ident`; the build
uses the pinned upstream workspace's API 26 toolchain and rejects any ELF note
or manifest disagreement with that minimum.

Before publication, it verifies that both files are 32-bit Intel Android ELF
shared libraries, have 16 KiB LOAD alignment, export the expected split
runtime/JNI symbol sets, and have no EGL, GLES, OpenCL, Vulkan, or unexpected
dynamic dependencies. The runtime SONAME must be `libLiteRt.so`; the JNI
SONAME must be `liblitert_jni.so`.

The workflow then validates two layouts on an API 26 pure-x86 emulator. The
first packages both libraries in the conventional APK native directory and
runs the upstream dynamic-shape add model. The second target APK packages the
exact JNI library but excludes the x86 LiteRT core; its instrumentation APK
carries both SO files as inert assets. One process copies the pair into
app-private storage, a fresh process loads both files there by absolute path,
and a third process loads the private core before the upstream API loads the
identical packaged JNI and runs the model. The process is force-stopped between
each phase. The inference tests require CPU discovery, successful compilation
and execution, finite outputs, and element-wise numerical agreement at `1e-5`
tolerance.

The packaged JNI is necessary only because the unmodified upstream 2.2 API
hard-codes `System.loadLibrary("litert_jni")`. The separate absolute-pair phase
still proves that the downloadable core and JNI can both be loaded from the
app-private directory. Booming SS's patched API loader is validated separately
with the downloadable bundle.

The app-private test reproduces the Booming SS downloadable layout and guards
the failure found in `2.2.0-bss.1`, where JNI requested `libLiteRt.so` but the
loaded x86 core advertised the noncanonical SONAME `LiteRt`.

This release does not reuse the LiteRT 2.1.5 UVR result. Full source-separation
presets remain outside the supported 32-bit x86 contract until separately
revalidated against this exact pair of binaries.
