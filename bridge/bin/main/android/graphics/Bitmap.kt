@file:Suppress("unused")
package android.graphics

import java.io.InputStream

/**
 * Minimal Bitmap stub for desktop JVM.
 * Some extensions reference Bitmap for image processing.
 */
class Bitmap {
    var width: Int = 0
    var height: Int = 0

    fun recycle() {}
    fun isRecycled(): Boolean = false

    companion object {
        @JvmStatic
        fun createBitmap(width: Int, height: Int, config: Config): Bitmap {
            return Bitmap().apply {
                this.width = width
                this.height = height
            }
        }
    }

    enum class Config {
        ALPHA_8, RGB_565, ARGB_4444, ARGB_8888, RGBA_F16, HARDWARE
    }

    enum class CompressFormat {
        JPEG, PNG, WEBP, WEBP_LOSSY, WEBP_LOSSLESS
    }
}

/**
 * Minimal BitmapFactory stub.
 */
class BitmapFactory {
    companion object {
        @JvmStatic
        fun decodeStream(input: InputStream?): Bitmap? {
            // Can't actually decode on JVM without a real image library
            return Bitmap()
        }

        @JvmStatic
        fun decodeByteArray(data: ByteArray?, offset: Int, length: Int): Bitmap? {
            return Bitmap()
        }
    }
}
