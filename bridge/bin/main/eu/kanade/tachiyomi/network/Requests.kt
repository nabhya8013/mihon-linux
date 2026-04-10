package eu.kanade.tachiyomi.network

import okhttp3.CacheControl
import okhttp3.FormBody
import okhttp3.Headers
import okhttp3.HttpUrl
import okhttp3.Request
import okhttp3.RequestBody

/**
 * Common OkHttp GET/POST/PUT/DELETE builders used by Tachiyomi extensions.
 * Extensions use both String and HttpUrl overloads, so both must be provided.
 * In Kotlin, these file-level functions compile down to RequestsKt.class
 */

// ── GET ──────────────────────────────────────────────────────────────────

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

fun GET(
    url: HttpUrl,
    headers: Headers = Headers.Builder().build(),
    cache: CacheControl = CacheControl.Builder().build()
): Request {
    return Request.Builder()
        .url(url)
        .headers(headers)
        .cacheControl(cache)
        .build()
}

// ── POST ─────────────────────────────────────────────────────────────────

fun POST(
    url: String, 
    headers: Headers = Headers.Builder().build(), 
    body: RequestBody = FormBody.Builder().build(),
    cache: CacheControl = CacheControl.Builder().build()
): Request {
    return Request.Builder()
        .url(url)
        .post(body)
        .headers(headers)
        .cacheControl(cache)
        .build()
}

fun POST(
    url: HttpUrl,
    headers: Headers = Headers.Builder().build(),
    body: RequestBody = FormBody.Builder().build(),
    cache: CacheControl = CacheControl.Builder().build()
): Request {
    return Request.Builder()
        .url(url)
        .post(body)
        .headers(headers)
        .cacheControl(cache)
        .build()
}

// ── PUT ──────────────────────────────────────────────────────────────────

fun PUT(
    url: String,
    headers: Headers = Headers.Builder().build(),
    body: RequestBody = FormBody.Builder().build(),
    cache: CacheControl = CacheControl.Builder().build()
): Request {
    return Request.Builder()
        .url(url)
        .put(body)
        .headers(headers)
        .cacheControl(cache)
        .build()
}

fun PUT(
    url: HttpUrl,
    headers: Headers = Headers.Builder().build(),
    body: RequestBody = FormBody.Builder().build(),
    cache: CacheControl = CacheControl.Builder().build()
): Request {
    return Request.Builder()
        .url(url)
        .put(body)
        .headers(headers)
        .cacheControl(cache)
        .build()
}

// ── DELETE ────────────────────────────────────────────────────────────────

fun DELETE(
    url: String,
    headers: Headers = Headers.Builder().build(),
    body: RequestBody? = FormBody.Builder().build(),
    cache: CacheControl = CacheControl.Builder().build()
): Request {
    return Request.Builder()
        .url(url)
        .delete(body)
        .headers(headers)
        .cacheControl(cache)
        .build()
}

fun DELETE(
    url: HttpUrl,
    headers: Headers = Headers.Builder().build(),
    body: RequestBody? = FormBody.Builder().build(),
    cache: CacheControl = CacheControl.Builder().build()
): Request {
    return Request.Builder()
        .url(url)
        .delete(body)
        .headers(headers)
        .cacheControl(cache)
        .build()
}
