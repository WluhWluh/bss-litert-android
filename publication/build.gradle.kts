import org.gradle.api.publish.maven.tasks.GenerateMavenPom
import org.gradle.api.publish.tasks.GenerateModuleMetadata

plugins {
    `maven-publish`
    signing
}

fun readEnvironmentFile(path: File): Map<String, String> =
    path.readLines()
        .map(String::trim)
        .filter { it.isNotEmpty() && !it.startsWith("#") }
        .associate { line ->
            val separator = line.indexOf('=')
            require(separator > 0) { "Invalid environment entry: $line" }
            line.substring(0, separator) to line.substring(separator + 1)
        }

val release = readEnvironmentFile(rootDir.resolve("../config/complete-runtime.env"))
group = release.getValue("MAVEN_GROUP")
version = providers.gradleProperty("artifactVersion")
    .orElse(release.getValue("ARTIFACT_VERSION"))
    .get()

val publishedArtifactId = release.getValue("MAVEN_ARTIFACT")
val inputDir = file(
    providers.gradleProperty("publicationInputDir")
        .orElse(layout.buildDirectory.dir("inputs").map { it.asFile.absolutePath })
        .get()
)
val stagingDir = file(
    providers.gradleProperty("stagingRepositoryDir")
        .orElse(layout.buildDirectory.dir("staging-repo").map { it.asFile.absolutePath })
        .get()
)
val prefix = "$publishedArtifactId-$version"

fun input(name: String): File = inputDir.resolve(name)

val publicationFiles = listOf(
    input("$prefix.aar"),
    input("$prefix-sources.jar"),
    input("$prefix-javadoc.jar"),
    input("$prefix.module"),
    input("$prefix-cyclonedx.json"),
    input("$prefix-build-manifest.json"),
    input("$prefix-third-party-licenses.txt"),
    input("$prefix-notices.txt"),
)

val validatePublicationInputs by tasks.registering {
    inputs.files(publicationFiles)
    doLast {
        val missing = publicationFiles.filterNot(File::isFile)
        check(missing.isEmpty()) {
            "Missing publication inputs: ${missing.joinToString()}"
        }
    }
}

publishing {
    publications {
        create<MavenPublication>("litertAndroid") {
            groupId = project.group.toString()
            artifactId = publishedArtifactId
            version = project.version.toString()

            artifact(input("$prefix.aar")) { extension = "aar" }
            artifact(input("$prefix-sources.jar")) {
                classifier = "sources"
                extension = "jar"
            }
            artifact(input("$prefix-javadoc.jar")) {
                classifier = "javadoc"
                extension = "jar"
            }
            artifact(input("$prefix.module")) { extension = "module" }
            artifact(input("$prefix-cyclonedx.json")) {
                classifier = "cyclonedx"
                extension = "json"
            }
            artifact(input("$prefix-build-manifest.json")) {
                classifier = "build-manifest"
                extension = "json"
            }
            artifact(input("$prefix-third-party-licenses.txt")) {
                classifier = "third-party-licenses"
                extension = "txt"
            }
            artifact(input("$prefix-notices.txt")) {
                classifier = "notices"
                extension = "txt"
            }

            pom {
                name = "Booming SS LiteRT Android runtime"
                description =
                    "Source-built LiteRT Android runtime used by Booming SS."
                url = "https://github.com/WluhWluh/bss-litert-android"
                packaging = "aar"
                licenses {
                    license {
                        name = "The Apache License, Version 2.0"
                        url = "https://www.apache.org/licenses/LICENSE-2.0.txt"
                        distribution = "repo"
                    }
                }
                developers {
                    developer {
                        id = "WluhWluh"
                        name = "WluhWluh"
                        url = "https://github.com/WluhWluh"
                    }
                }
                scm {
                    connection =
                        "scm:git:https://github.com/WluhWluh/bss-litert-android.git"
                    developerConnection =
                        "scm:git:ssh://git@github.com/WluhWluh/bss-litert-android.git"
                    url = "https://github.com/WluhWluh/bss-litert-android"
                }
            }
        }
    }
    repositories {
        maven {
            name = "localStaging"
            url = uri(stagingDir)
        }
    }
}

tasks.withType<GenerateModuleMetadata>().configureEach {
    enabled = false
}
tasks.withType<GenerateMavenPom>().configureEach {
    dependsOn(validatePublicationInputs)
}
tasks.matching { it.name.startsWith("publish") }.configureEach {
    dependsOn(validatePublicationInputs)
}

val signingKey = providers.environmentVariable("MAVEN_SIGNING_KEY")
val signingPassword = providers.environmentVariable("MAVEN_SIGNING_PASSWORD")
if (signingKey.isPresent) {
    signing {
        useInMemoryPgpKeys(signingKey.get(), signingPassword.orNull)
        sign(publishing.publications["litertAndroid"])
    }
}
