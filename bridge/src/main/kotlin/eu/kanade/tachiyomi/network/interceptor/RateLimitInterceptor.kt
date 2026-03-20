@file:JvmName("RateLimitInterceptorKt")
package eu.kanade.tachiyomi.network.interceptor

import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/**
 * No-op rate limiter. On desktop we don't need the Android rate-limiter;
 * real network throttling (if desired) can be added later.
 */
fun OkHttpClient.Builder.rateLimit(
    permits: Int,
    period: Long = 1,
    unit: TimeUnit = TimeUnit.SECONDS
): OkHttpClient.Builder = this
