#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

version="$(cat VERSION)"
app_apk="smoke/app/build/outputs/apk/debug/app-debug.apk"
test_apk="smoke/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
runner="io.github.wluhwluh.bss.litert.smoke.test/androidx.test.runner.AndroidJUnitRunner"

./smoke/gradlew -p smoke assembleDebug assembleDebugAndroidTest --stacktrace
adb install --no-streaming -r "${app_apk}"
adb install --no-streaming -r "${test_apk}"
adb shell am instrument -w -r \
    -e class io.github.wluhwluh.bss.litert.smoke.LiteRtX86SmokeTest \
    "${runner}" | tee dist/api26-x86-smoke.txt
grep -Fq 'OK (1 test)' dist/api26-x86-smoke.txt

rm -rf smoke/app/src/main/jniLibs
mkdir -p smoke/app/src/main/jniLibs/x86
cp "dist/liblitert_jni-${version}-android-x86.so" \
    smoke/app/src/main/jniLibs/x86/liblitert_jni.so
mkdir -p smoke/app/src/androidTest/assets
cp "dist/libLiteRt-${version}-android-x86.so" \
    smoke/app/src/androidTest/assets/libLiteRt.so
cp "dist/liblitert_jni-${version}-android-x86.so" \
    smoke/app/src/androidTest/assets/liblitert_jni.so
./smoke/gradlew -p smoke clean assembleDebug assembleDebugAndroidTest --stacktrace
apk_entries="$(unzip -Z1 "${app_apk}")"
if grep -Fq 'lib/x86/libLiteRt.so' <<< "${apk_entries}"; then
    echo 'Private-core smoke APK contains a packaged x86 LiteRT core.' >&2
    exit 1
fi
grep -Fxq 'lib/x86/liblitert_jni.so' <<< "${apk_entries}"

adb uninstall io.github.wluhwluh.bss.litert.smoke.test || true
adb uninstall io.github.wluhwluh.bss.litert.smoke || true
adb install --no-streaming -r "${app_apk}"
adb install --no-streaming -r "${test_apk}"
adb shell am instrument -w -r \
    -e class 'io.github.wluhwluh.bss.litert.smoke.LiteRtX86PrivatePathSmokeTest#installsLibrariesInAppPrivateStorage' \
    "${runner}" | tee dist/api26-x86-private-install.txt
grep -Fq 'OK (1 test)' dist/api26-x86-private-install.txt
adb shell am force-stop io.github.wluhwluh.bss.litert.smoke
adb shell am instrument -w -r \
    -e class 'io.github.wluhwluh.bss.litert.smoke.LiteRtX86PrivatePathSmokeTest#loadsPreviouslyInstalledPairByAbsolutePath' \
    "${runner}" | tee dist/api26-x86-private-load.txt
grep -Fq 'OK (1 test)' dist/api26-x86-private-load.txt
adb shell am force-stop io.github.wluhwluh.bss.litert.smoke
adb shell am instrument -w -r \
    -e class 'io.github.wluhwluh.bss.litert.smoke.LiteRtX86PrivatePathSmokeTest#runsAddModelWithPrivateCoreAndPackagedJni' \
    "${runner}" | tee dist/api26-x86-private-smoke.txt
grep -Fq 'OK (1 test)' dist/api26-x86-private-smoke.txt
