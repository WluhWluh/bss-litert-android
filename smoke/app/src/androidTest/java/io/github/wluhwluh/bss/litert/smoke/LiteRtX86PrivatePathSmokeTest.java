package io.github.wluhwluh.bss.litert.smoke;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.zip.ZipFile;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public final class LiteRtX86PrivatePathSmokeTest {
    @Test
    public void installsLibrariesInAppPrivateStorage() throws Exception {
        Context testContext = InstrumentationRegistry.getInstrumentation().getContext();
        Context targetContext = InstrumentationRegistry.getInstrumentation().getTargetContext();
        File runtimeDirectory = runtimeDirectory(targetContext);
        File runtime = copyAsset(testContext, runtimeDirectory, "libLiteRt.so");
        File jni = copyAsset(testContext, runtimeDirectory, "liblitert_jni.so");
        assertTrue(runtime.setReadOnly());
        assertTrue(jni.setReadOnly());
    }

    @Test
    public void loadsPreviouslyInstalledPairByAbsolutePath() throws Exception {
        Context targetContext = InstrumentationRegistry.getInstrumentation().getTargetContext();
        File runtimeDirectory = runtimeDirectory(targetContext);
        File runtime = new File(runtimeDirectory, "libLiteRt.so");
        File jni = new File(runtimeDirectory, "liblitert_jni.so");
        assertTrue(runtime.isFile());
        assertTrue(jni.isFile());

        System.load(runtime.getCanonicalPath());
        System.load(jni.getCanonicalPath());
    }

    @Test
    public void runsAddModelWithPrivateCoreAndPackagedJni() throws Exception {
        Context targetContext = InstrumentationRegistry.getInstrumentation().getTargetContext();
        try (ZipFile apk = new ZipFile(targetContext.getApplicationInfo().sourceDir)) {
            assertFalse(
                    apk.stream().anyMatch(
                            entry -> entry.getName().matches(
                                    "lib/x86/libLiteRt\\.so"))
            );
            assertTrue(
                    apk.stream().anyMatch(
                            entry -> entry.getName().matches(
                                    "lib/x86/liblitert_jni\\.so"))
            );
        }

        File runtimeDirectory = runtimeDirectory(targetContext);
        File runtime = new File(runtimeDirectory, "libLiteRt.so");
        assertTrue(runtime.isFile());

        System.load(runtime.getCanonicalPath());
        LiteRtX86SmokeTest.runAddModelWithCpuAccelerator();
    }

    private static File runtimeDirectory(Context context) {
        File directory = new File(context.getNoBackupFilesDir(), "litert-private-x86");
        assertTrue(directory.isDirectory() || directory.mkdirs());
        return directory;
    }

    private static File copyAsset(Context context, File directory, String name) throws Exception {
        File target = new File(directory, name);
        assertTrue(!target.exists() || target.delete());
        try (InputStream input = context.getAssets().open(name);
                FileOutputStream output = new FileOutputStream(target)) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) {
                output.write(buffer, 0, count);
            }
        }
        return target;
    }
}
