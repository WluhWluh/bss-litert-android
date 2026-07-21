plugins {
    id("com.android.application")
}

android {
    namespace = "io.github.wluhwluh.bss.litert.smoke"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.wluhwluh.bss.litert.smoke"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

}

dependencies {
    implementation("com.google.ai.edge.litert:litert:2.1.5")

    androidTestImplementation("androidx.test.ext:junit-ktx:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
}
