@file:Suppress("unused")
package okhttp3.brotli

import okhttp3.CompressionInterceptor
import okhttp3.Interceptor
import okhttp3.Response

/**
 * `okhttp3.brotli.Brotli` / `BrotliInterceptor`.
 *
 * Extensions pass `Brotli` into CompressionInterceptor and separately assert
 * that `BrotliInterceptor` is NOT installed on the default client, so both
 * types must exist. No brotli decoder is bundled, so the algorithm reports
 * itself unsupported and `br` is never advertised.
 */
object Brotli : CompressionInterceptor.DecompressionAlgorithm {
    override val encoding: String = "br"
    override val isSupported: Boolean = false
}

object BrotliInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response = chain.proceed(chain.request())
}
