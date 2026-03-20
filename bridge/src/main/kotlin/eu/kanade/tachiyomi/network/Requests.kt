package eu.kanade.tachiyomi.network

import okhttp3.CacheControl
import okhttp3.FormBody
import okhttp3.Headers
import okhttp3.Request
import okhttp3.RequestBody

/**
 * Common OkHttp GET/POST builders used by Tachiyomi extensions.
 * In Kotlin, these file-level functions compile down to RequestsKt.class
 */

fun GET(
    url: String, 
    headers: Headers = Headers.Builder().build(), 
    cache: CacheControl = CacheControl.Builder().build()
): Request {
    return Request.Builder()
        .url(url)
        .headers(headers)
        .cacheControl(cache)
        .build()
}

fun POST(
    url: String, 
    headers: Headers = Headers.Builder().build(), 
    body: RequestBody = FormBody.Builder().build()
): Request {
    return Request.Builder()
        .url(url)
        .post(body)
        .headers(headers)
        .build()
}
