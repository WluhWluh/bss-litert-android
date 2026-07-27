pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        providers.gradleProperty("litertStagingRepository").orNull?.let {
            maven { url = uri(it) }
        }
        google()
        mavenCentral()
    }
}

rootProject.name = "LiteRtX86Smoke"
include(":app")
include(":contract")
