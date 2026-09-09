@file:Suppress("unused")
package okhttp3

import java.util.zip.GZIPInputStream
import java.util.zip.Inflater
import java.util.zip.InflaterInputStream
import okhttp3.ResponseBody.Companion.asResponseBody
import okio.buffer
import okio.source

/**
 * `okhttp3.CompressionInterceptor` — declared by Mihon in the `okhttp3` package,
 * not by OkHttp itself, so the bridge has to supply it.
 *
 * Extensions construct it as
 * `CompressionInterceptor(Brotli, Gzip, Zstd)` and assert it on the shared
 * client. Only algorithms this JVM can actually decode are advertised in
 * `Accept-Encoding`; requesting `br`/`zstd` without a decoder would leave us
 * with an undecodable body.
 */
class CompressionInterceptor(
    private vararg val algorithms: DecompressionAlgorithm,
) : Interceptor {

    /** Marker for one supported content encoding. */
    interface DecompressionAlgorithm {
        val encoding: String

        /** True when this JVM can actually decode the encoding. */
        val isSupported: Boolean get() = false

        fun decompress(body: ResponseBody): ResponseBody = body
    }

    private val acceptEncoding: String =
        (algorithms.filter { it.isSupported }.map { it.encoding } + DEFLATE)
            .distinct()
            .joinToString(", ")

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val response = if (request.header("Accept-Encoding") == null) {
            chain.proceed(
                request.newBuilder().header("Accept-Encoding", acceptEncoding).build(),
            )
        } else {
            return chain.proceed(request)
        }

        val encoding = response.header("Content-Encoding")?.lowercase() ?: return response
        val body = response.body ?: return response

        val decoded = when (encoding) {
            "gzip" -> GZIPInputStream(body.byteStream())
            "deflate" -> InflaterInputStream(body.byteStream(), Inflater(true))
            else -> algorithms.firstOrNull { it.encoding == encoding && it.isSupported }
                ?.let { return response.newBuilder().body(it.decompress(body)).build() }
                ?: return response
        }

        return response.newBuilder()
            .removeHeader("Content-Encoding")
            .removeHeader("Content-Length")
            .body(decoded.source().buffer().asResponseBody(body.contentType(), -1L))
            .build()
    }

    private companion object {
        const val DEFLATE = "deflate"
    }
}

/** `okhttp3.Gzip` — the one algorithm always available on a stock JVM. */
object Gzip : CompressionInterceptor.DecompressionAlgorithm {
    override val encoding: String = "gzip"
    override val isSupported: Boolean = true
}
