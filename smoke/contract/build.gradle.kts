plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

android {
    namespace = "io.github.wluhwluh.bss.litert.contract"
    compileSdk = 35

    defaultConfig {
        minSdk = 23
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    val candidateAar = providers.gradleProperty("litertContractAar").orNull
    if (candidateAar == null) {
        compileOnly("com.google.ai.edge.litert:litert:2.1.5")
    } else {
        compileOnly(files(candidateAar))
        compileOnly("org.jetbrains.kotlin:kotlin-stdlib:2.3.21")
    }
}
