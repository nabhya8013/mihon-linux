package org.mihon.bridge

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*

/**
 * JSON-RPC 2.0 protocol models.
 */

@Serializable
data class JsonRpcRequest(
    val jsonrpc: String = "2.0",
    val method: String,
    val params: JsonObject = JsonObject(emptyMap()),
    val id: Int? = null,
)

@Serializable
data class JsonRpcResponse(
    val jsonrpc: String = "2.0",
    val id: Int? = null,
    val result: JsonElement? = null,
    val error: JsonRpcError? = null,
)

@Serializable
data class JsonRpcError(
    val code: Int,
    val message: String,
    val data: JsonElement? = null,
) {
    companion object {
        // Standard JSON-RPC error codes
        const val PARSE_ERROR = -32700
        const val INVALID_REQUEST = -32600
        const val METHOD_NOT_FOUND = -32601
        const val INVALID_PARAMS = -32602
        const val INTERNAL_ERROR = -32603

        // Custom error codes
        const val EXTENSION_NOT_FOUND = -32001
        const val EXTENSION_LOAD_FAILED = -32002
        const val EXTENSION_METHOD_ERROR = -32003

        fun parseError(msg: String) = JsonRpcError(PARSE_ERROR, msg)
        fun methodNotFound(method: String) = JsonRpcError(METHOD_NOT_FOUND, "Method not found: $method")
        fun invalidParams(msg: String) = JsonRpcError(INVALID_PARAMS, msg)
        fun internalError(msg: String) = JsonRpcError(INTERNAL_ERROR, msg)
        fun extensionNotFound(id: String) = JsonRpcError(EXTENSION_NOT_FOUND, "Extension not found: $id")
        fun extensionLoadFailed(msg: String) = JsonRpcError(EXTENSION_LOAD_FAILED, msg)
        fun extensionError(msg: String) = JsonRpcError(EXTENSION_METHOD_ERROR, msg)
    }
}
