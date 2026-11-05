package eu.kanade.tachiyomi.network.interceptor

import okhttp3.Interceptor
import okhttp3.Response

/**
 * Adds baseline browser-like headers when missing. Some sites/WAFs block
 * requests that lack Accept/Accept-Language/Sec-Fetch hints. Extensions may
 * still override per-request.
 */
class BrowserHeadersInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val req = chain.request()
        val b = req.newBuilder()
        fun set(name: String, value: String) {
            if (req.header(name).isNullOrBlank()) b.header(name, value)
        }
        set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8")
        set("Accept-Language", "en-US,en;q=0.9")
        set("Upgrade-Insecure-Requests", "1")
        set("Sec-Fetch-Dest", "document")
        set("Sec-Fetch-Mode", "navigate")
        set("Sec-Fetch-Site", "none")
        set("Sec-Fetch-User", "?1")
        return chain.proceed(b.build())
    }
}
