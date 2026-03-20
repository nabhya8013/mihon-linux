plugins {
    kotlin("jvm") version "1.9.22"
    kotlin("plugin.serialization") version "1.9.22"
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
    implementation("com.squareup.okhttp3:okhttp:5.0.0-alpha.12")
    implementation("org.jsoup:jsoup:1.17.2")

    // Coroutines (for suspend-based extension API)
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.0")

    // RxJava 1 (older tachiyomi extensions use rx.Observable)
    implementation("io.reactivex:rxjava:1.3.8")

    // Serialization (JSON-RPC wire format)
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")

    // Testing
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
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
