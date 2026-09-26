package eu.kanade.tachiyomi.network

/**
 * Thrown by `Call.awaitSuccess()` / `asObservableSuccess()` on a non-2xx
 * response. Extensions catch it to convert HTTP failures into friendly
 * messages, so the type must exist even when nothing throws it.
 */
class HttpException(val code: Int) : IllegalStateException("HTTP error $code")
