plugins {
    id("com.android.application")
    id("com.chaquo.python") version "17.2.0"
}

val repoRoot = rootProject.projectDir.parentFile
val frontendDist = repoRoot.resolve("frontend/dist")
val knowledgeSource = repoRoot.resolve("knowledge")
val appSource = repoRoot.resolve("app")
val generatedAssetsDir = layout.buildDirectory.dir("generated/bundledAssets").get().asFile
val pythonDestinationDir = layout.projectDirectory.dir("src/main/python/app").asFile

// Only pure mobile modules are copied. Desktop-only modules (FastAPI/Pydantic/
// DPAPI/Node) and any data directory are deliberately absent.
val mobilePythonModules = listOf(
    "__init__", "engine", "formula_engine", "decision", "decision_support",
    "library", "knowledge", "storage", "consultation_core", "domain",
    "portable_validation", "model_profiles", "model_urls", "mobile_models",
    "mobile_api", "offline_pack", "offline_runtime",
)

val syncPythonSources = tasks.register<Sync>("syncPythonSources") {
    into(pythonDestinationDir)
    from(appSource) {
        include(mobilePythonModules.map { "$it.py" })
    }
    from(appSource.resolve("resources")) {
        include("**/*.json")
        into("resources")
    }
    doFirst {
        val missing = mobilePythonModules.filterNot { appSource.resolve("$it.py").isFile }
        if (missing.isNotEmpty()) {
            throw GradleException(
                "Missing mobile Python modules under ${appSource}: " +
                    missing.joinToString { "$it.py" } +
                    ". The parent build must supply them before assembling.",
            )
        }
    }
}

val syncBundledAssets = tasks.register<Sync>("syncBundledAssets") {
    into(generatedAssetsDir)
    from(frontendDist)
    if (knowledgeSource.isDirectory) {
        from(knowledgeSource) { into("knowledge") }
    }
    doFirst {
        if (!frontendDist.resolve("index.html").isFile) {
            throw GradleException(
                "frontend/dist/index.html is missing. Build the Vue bundle before assembling the APK.",
            )
        }
        val bundledKnowledge = layout.projectDirectory.dir("src/main/assets/knowledge").asFile
        if (!knowledgeSource.isDirectory && !bundledKnowledge.isDirectory) {
            throw GradleException(
                "No knowledge pack found at $knowledgeSource or src/main/assets/knowledge. " +
                    "The parent build must copy the packaged knowledge assets first.",
            )
        }
    }
}

android {
    namespace = "com.nihaixia.local"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.nihaixia.local"
        minSdk = 26
        targetSdk = 35
        versionCode = 50
        versionName = "0.5.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    signingConfigs {
        getByName("debug") {
            // Stable local-only debug signing cache under the project .cache directory,
            // created by scripts/build_android_offline.ps1 before Gradle runs.
            val keystore = repoRoot.resolve(".cache/android-user-home/debug.keystore")
            if (keystore.isFile) {
                storeFile = keystore
                storePassword = "android"
                keyAlias = "androiddebugkey"
                keyPassword = "android"
            }
        }
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
        }
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets.getByName("main").assets.srcDir(generatedAssetsDir)

    lint {
        abortOnError = true
        checkReleaseBuilds = false
    }
}

chaquopy {
    defaultConfig {
        version = "3.11"
        buildPython(
            providers.gradleProperty("buildPython").orNull
                ?: providers.environmentVariable("NIHAIXIA_BUILD_PYTHON").orNull
                ?: "D:/Python311/python.exe",
        )
        pip {
            install("fastjsonschema==2.21.2")
        }
        extractPackages("app")
    }
}

tasks.named("preBuild") {
    dependsOn(syncPythonSources, syncBundledAssets)
}

tasks.matching { it.name.startsWith("merge") && it.name.endsWith("PythonSources") }.configureEach {
    dependsOn(syncPythonSources)
}

dependencies {
    implementation("androidx.core:core:1.13.1")
    implementation("androidx.webkit:webkit:1.12.1")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
