package eu.kanade.tachiyomi.network

import java.net.URI
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.exists
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import eu.kanade.tachiyomi.network.interceptor.CloudflareInterceptor

/**
 * Stub NetworkHelper that provides OkHttpClient instances.
 * Many extensions use `network.client` or `network.cloudflareClient`.
 */
class NetworkHelper {

    val client: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .addInterceptor(SyncedUserAgentInterceptor())
            .addInterceptor(CloudflareInterceptor())
            .connectTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
            .writeTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
            .build()
    }

    // The CF-aware client now exists: same as `client` but explicitly
    // exposed for extensions that opt into the Cloudflare-protected path.
    val cloudflareClient: OkHttpClient
        get() = client
}

private class SyncedUserAgentInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        val request = chain.request()
        val syncedUserAgent = SharedUserAgentStore.userAgentForUrl(request.url.toString())
        if (syncedUserAgent.isBlank()) {
            return chain.proceed(request)
        }
        return chain.proceed(
            request.newBuilder()
                .header("User-Agent", syncedUserAgent)
                .build()
        )
    }
}

private object SharedUserAgentStore {
    private val json = Json { ignoreUnknownKeys = true }
    private val sharedJarPath: Path? = System.getenv("MIHON_COOKIE_JAR")
        ?.takeIf { it.isNotBlank() }
        ?.let { Path.of(it) }

    fun userAgentForUrl(url: String): String {
        val host = runCatching { URI(url).host?.lowercase() }.getOrNull() ?: return ""
        return loadJar().user_agents
            .filter { host == it.domain || host.endsWith(".${it.domain}") }
            .maxByOrNull { it.domain.length }
            ?.user_agent
            .orEmpty()
    }

    private fun loadJar(): SharedCookieJar {
        val path = sharedJarPath ?: return SharedCookieJar()
        if (!path.exists()) return SharedCookieJar()
        return runCatching {
            json.decodeFromString<SharedCookieJar>(Files.readString(path))
        }.getOrDefault(SharedCookieJar())
    }
}

@Serializable
private data class SharedCookieJar(
    val user_agents: List<SharedUserAgentRecord> = emptyList(),
)

@Serializable
private data class SharedUserAgentRecord(
    val domain: String,
    val user_agent: String,
    val updated_at: Double = 0.0,
)
