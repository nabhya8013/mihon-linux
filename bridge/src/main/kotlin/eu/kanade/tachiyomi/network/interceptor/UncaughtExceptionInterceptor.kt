package eu.kanade.tachiyomi.network.interceptor

import java.io.IOException
import okhttp3.Interceptor
import okhttp3.Response

/**
 * Converts any non-IOException thrown inside the interceptor chain into an
 * IOException, which is the only failure type OkHttp callers expect.
 *
 * Extensions-lib asserts this interceptor is present on the shared client and
 * refuses to issue a request otherwise ("UncaughtExceptionInterceptor must be
 * present in default client"), so its absence made most sources fail outright.
 */
class UncaughtExceptionInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        return try {
            chain.proceed(chain.request())
        } catch (e: Exception) {
            throw if (e is IOException) e else IOException(e)
        }
    }
}
