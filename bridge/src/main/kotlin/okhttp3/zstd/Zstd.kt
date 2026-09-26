@file:Suppress("unused")
package okhttp3.zstd

import okhttp3.CompressionInterceptor

/**
 * `okhttp3.zstd.Zstd`. No zstd decoder is bundled, so it is declared but never
 * advertised in Accept-Encoding.
 */
object Zstd : CompressionInterceptor.DecompressionAlgorithm {
    override val encoding: String = "zstd"
    override val isSupported: Boolean = false
}
