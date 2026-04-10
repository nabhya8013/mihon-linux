package eu.kanade.tachiyomi.network

import okhttp3.OkHttpClient

/**
 * Stub NetworkHelper that provides OkHttpClient instances.
 * Many extensions use `network.client` or `network.cloudflareClient`.
 */
class NetworkHelper {

    val client: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
            .writeTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
            .build()
    }

    // Since we don't implement Cloudflare bypass on JVM yet, 
    // just return the normal client.
    val cloudflareClient: OkHttpClient
        get() = client
}
