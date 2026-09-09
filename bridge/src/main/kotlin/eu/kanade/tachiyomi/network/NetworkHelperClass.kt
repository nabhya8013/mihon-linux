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
import eu.kanade.tachiyomi.network.interceptor.UncaughtExceptionInterceptor
import eu.kanade.tachiyomi.network.interceptor.UserAgentInterceptor

/**
 * Stub NetworkHelper that provides OkHttpClient instances.
 * Many extensions use `network.client` or `network.cloudflareClient`.
 */
class NetworkHelper {

    /**
     * Shared persistent cookie jar. Extensions reach it as `network.cookieJar`;
     * OkHttp uses it for every request so a solved challenge keeps working.
     */
    val cookieJar: AndroidCookieJar = AndroidCookieJar()

    val client: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .cookieJar(cookieJar)
            // Must be first: extensions-lib checks for it before issuing any
            // request and aborts the call when it is missing.
            .addInterceptor(UncaughtExceptionInterceptor())
            .addInterceptor(UserAgentInterceptor())
            .addInterceptor(CloudflareInterceptor())
            .apply {
                // Opt-in wire log: MIHON_HTTP_LOG=1 prints every extension
                // request/response to stderr. Invaluable when a source returns
                // an empty list and gives no other clue why.
                if (System.getenv("MIHON_HTTP_LOG") == "1") {
                    addNetworkInterceptor(RequestLogInterceptor())
                }
            }
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

private class RequestLogInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        val request = chain.request()
        val started = System.currentTimeMillis()
        val response = chain.proceed(request)
        System.err.println(
            "[http] ${request.method} ${response.code} " +
                "(${System.currentTimeMillis() - started}ms) ${request.url}"
        )
        return response
    }
}

internal object SharedUserAgentStore {
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
