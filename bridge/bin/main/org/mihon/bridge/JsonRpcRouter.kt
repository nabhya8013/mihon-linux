package org.mihon.bridge

import kotlinx.serialization.json.*

/**
 * Routes incoming JSON-RPC requests to the appropriate handler based on method prefix.
 *
 * Method routing:
 *   system.*    → SystemHandler
 *   extension.* → ExtensionHandler
 */
object JsonRpcRouter {

    /**
     * Parse a raw JSON line and route it to the appropriate handler.
     * Returns a JSON-RPC response string (always a single line, no newlines).
     */
    fun route(rawLine: String): String {
        // 1. Parse JSON
        val request: JsonRpcRequest
        try {
            request = bridgeJson.decodeFromString<JsonRpcRequest>(rawLine)
        } catch (e: Exception) {
            return makeErrorResponse(null, JsonRpcError.parseError("Invalid JSON: ${e.message}"))
        }

        // 2. Validate
        if (request.method.isBlank()) {
            return makeErrorResponse(request.id, JsonRpcError(JsonRpcError.INVALID_REQUEST, "Empty method"))
        }

        // 3. Route to handler
        try {
            val result = when {
                request.method.startsWith("system.") ->
                    SystemHandler.handle(request.method, request.params)

                request.method.startsWith("extension.") ->
                    ExtensionHandler.handle(request.method, request.params)

                else -> throw NoSuchMethodException(request.method)
            }

            return makeSuccessResponse(request.id, result)

        } catch (e: NoSuchMethodException) {
            return makeErrorResponse(request.id, JsonRpcError.methodNotFound(request.method))
        } catch (e: IllegalArgumentException) {
            return makeErrorResponse(request.id, JsonRpcError.invalidParams(e.message ?: "Invalid params"))
        } catch (e: Throwable) {
            System.err.println("[JsonRpcRouter] Error handling ${request.method}: ${e.message}")
            e.printStackTrace(System.err)
            return makeErrorResponse(
                request.id,
                JsonRpcError.internalError("${e::class.simpleName}: ${e.message}")
            )
        }
    }

    private fun makeSuccessResponse(id: Int?, result: JsonElement): String {
        val response = JsonRpcResponse(id = id, result = result)
        return bridgeJson.encodeToString(JsonRpcResponse.serializer(), response)
    }

    private fun makeErrorResponse(id: Int?, error: JsonRpcError): String {
        val response = JsonRpcResponse(id = id, error = error)
        return bridgeJson.encodeToString(JsonRpcResponse.serializer(), response)
    }
}
