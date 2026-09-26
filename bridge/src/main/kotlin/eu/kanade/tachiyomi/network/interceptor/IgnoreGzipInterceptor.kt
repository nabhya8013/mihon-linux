package eu.kanade.tachiyomi.network.interceptor

import okhttp3.Interceptor
import okhttp3.Response

/**
 * Strips a `Content-Encoding: gzip` header that some servers send on an already
 * decoded body, which would otherwise make OkHttp inflate the payload twice.
 * Part of Mihon's default interceptor chain, so extensions expect it to exist.
 */
class IgnoreGzipInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val response = chain.proceed(chain.request())
        if (response.headers["Content-Encoding"].equals("gzip", ignoreCase = true)) {
            return response.newBuilder().removeHeader("Content-Encoding").build()
        }
        return response
    }
}
