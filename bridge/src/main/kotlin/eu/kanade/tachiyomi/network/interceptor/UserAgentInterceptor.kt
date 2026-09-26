package eu.kanade.tachiyomi.network.interceptor

import eu.kanade.tachiyomi.network.SharedUserAgentStore
import okhttp3.Interceptor
import okhttp3.Response

/**
 * Applies a default User-Agent to requests that do not set one.
 *
 * The class name matters: extensions-lib asserts an interceptor of exactly this
 * type is installed on the shared client and refuses to run otherwise.
 *
 * On top of upstream behaviour this also replays the User-Agent that solved a
 * Cloudflare challenge for the request's domain, so the fingerprint the site
 * issued its clearance cookie to keeps matching.
 */
class UserAgentInterceptor(
    private val defaultUserAgentProvider: () -> String = { DEFAULT_USER_AGENT },
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()

        val syncedUserAgent = SharedUserAgentStore.userAgentForUrl(request.url.toString())
        if (syncedUserAgent.isNotBlank()) {
            return chain.proceed(
                request.newBuilder()
                    .removeHeader("User-Agent")
                    .addHeader("User-Agent", syncedUserAgent)
                    .build(),
            )
        }

        if (!request.header("User-Agent").isNullOrEmpty()) {
            return chain.proceed(request)
        }

        return chain.proceed(
            request.newBuilder()
                .removeHeader("User-Agent")
                .addHeader("User-Agent", defaultUserAgentProvider().trim())
                .build(),
        )
    }

    companion object {
        const val DEFAULT_USER_AGENT =
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) " +
                "Chrome/124.0.0.0 Safari/537.36"
    }
}
