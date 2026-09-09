plugins {
    kotlin("jvm") version "2.2.0"
    kotlin("plugin.serialization") version "2.2.0"
    application
}

group = "org.mihon"
version = "1.0-SNAPSHOT"

repositories {
    mavenCentral()
    maven("https://jitpack.io")
}

dependencies {
    // OkHttp & jsoup (used by extensions and our HttpSource stub)
    implementation("com.squareup.okhttp3:okhttp:5.1.0")
    implementation("org.jsoup:jsoup:1.17.2")

    // Coroutines (for suspend-based extension API)
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.0")

    // RxJava 1 (older tachiyomi extensions use rx.Observable)
    implementation("io.reactivex:rxjava:1.3.8")

    // Rhino — real JS engine behind the app.cash.quickjs shim. Extensions that
    // deobfuscate page URLs by evaluating site JavaScript need a working engine;
    // the previous stub returned null and made those sources fail silently.
    implementation("org.mozilla:rhino:1.7.15")
    implementation("org.mozilla:rhino-engine:1.7.15")

    // Serialization (JSON-RPC wire format)
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.1")
    // Extensions decode responses straight off the okio BufferedSource.
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json-okio:1.8.1")

    // Testing
    testImplementation(kotlin("test"))
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.2")
}

tasks.test {
    useJUnitPlatform()
    testLogging {
        events("passed", "skipped", "failed")
    }
}

// Build a fat JAR with all dependencies
tasks.jar {
    manifest {
        attributes["Main-Class"] = "org.mihon.bridge.MainKt"
    }
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    from(configurations.runtimeClasspath.get().map { if (it.isDirectory) it else zipTree(it) })
}

application {
    mainClass.set("org.mihon.bridge.MainKt")
}
