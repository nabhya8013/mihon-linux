package org.mihon.bridge

import kotlinx.serialization.json.Json
import uy.kohesive.injekt.Injekt

/**
 * Mihon JVM Bridge — Main entry point.
 *
 * Reads JSON-RPC 2.0 requests from stdin (one per line),
 * routes them through the JsonRpcRouter, and writes responses to stdout.
 *
 * Communication protocol:
 *   - Each request is a single JSON line on stdin
 *   - Each response is a single JSON line on stdout
 *   - stderr is used for logging/diagnostics
 *   - Sending "exit" or "quit" (plain text) shuts down the bridge
 */
fun main(args: Array<String>) {
    // ── Register Injekt singletons ──────────────────────────────────────
    // Extensions use Injekt.get<T>() / injectLazy() to resolve these.
    val app = android.app.Application()
    Injekt.addSingleton(app)
    Injekt.addSingleton<android.content.Context>(app)
    Injekt.addSingleton(eu.kanade.tachiyomi.network.NetworkHelper())
    Injekt.addSingleton(
        Json {
            ignoreUnknownKeys = true
            isLenient = true
            explicitNulls = false
            coerceInputValues = true
        }
    )
    System.err.println("[bridge] Injekt singletons registered.")
    System.err.println("═══════════════════════════════════════════════")
    System.err.println("  Mihon JVM Bridge v1.0.0")
    System.err.println("  Protocol: JSON-RPC 2.0 over stdin/stdout")
    System.err.println("  Java: ${System.getProperty("java.version")}")
    System.err.println("  Kotlin: ${KotlinVersion.CURRENT}")
    System.err.println("═══════════════════════════════════════════════")
    System.err.println("[bridge] Ready. Waiting for JSON-RPC requests on stdin...")

    // Signal readiness to the Python side
    println("""{"jsonrpc":"2.0","method":"bridge.ready","params":{"version":"1.0.0"}}""")
    System.out.flush()

    val reader = System.`in`.bufferedReader()

    while (true) {
        val line = try {
            reader.readLine()
        } catch (e: Exception) {
            System.err.println("[bridge] stdin read error: ${e.message}")
            break
        }

        // EOF or null → parent process closed stdin
        if (line == null) {
            System.err.println("[bridge] stdin closed (EOF). Shutting down.")
            break
        }

        val trimmed = line.trim()
        if (trimmed.isEmpty()) continue

        // Plain text exit commands
        if (trimmed == "exit" || trimmed == "quit") {
            System.err.println("[bridge] Exit command received. Shutting down.")
            println("""{"jsonrpc":"2.0","result":{"status":"exiting"}}""")
            System.out.flush()
            break
        }

        // Route through JSON-RPC router
        val response = JsonRpcRouter.route(trimmed)

        // Write response as single line to stdout
        println(response)
        System.out.flush()
    }

    // Cleanup
    ExtensionLoader.unloadAll()
    System.err.println("[bridge] Goodbye.")
}
