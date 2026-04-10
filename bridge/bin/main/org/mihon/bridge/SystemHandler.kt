package org.mihon.bridge

import kotlinx.serialization.json.*

/**
 * Handles system.* JSON-RPC methods — health checks, status, diagnostics.
 */
object SystemHandler {

    fun handle(method: String, params: JsonObject): JsonElement {
        return when (method) {
            "system.ping" -> handlePing()
            "system.status" -> handleStatus()
            "system.version" -> handleVersion()
            else -> throw NoSuchMethodException(method)
        }
    }

    private fun handlePing(): JsonElement {
        return buildJsonObject {
            put("pong", true)
            put("timestamp", System.currentTimeMillis())
        }
    }

    private fun handleStatus(): JsonElement {
        val sources = ExtensionLoader.getAllSources()
        return buildJsonObject {
            put("running", true)
            put("loadedExtensions", sources.size)
            put("extensions", buildJsonArray {
                for (src in sources) {
                    add(buildJsonObject {
                        put("id", src.id)
                        put("name", src.name)
                        put("lang", src.lang)
                    })
                }
            })
            put("jvmVersion", System.getProperty("java.version") ?: "unknown")
            put("memoryUsedMB", (Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory()) / 1_048_576)
        }
    }

    private fun handleVersion(): JsonElement {
        return buildJsonObject {
            put("bridge", "1.0.0")
            put("protocol", "jsonrpc-2.0")
            put("java", System.getProperty("java.version") ?: "unknown")
            put("kotlin", KotlinVersion.CURRENT.toString())
        }
    }
}
