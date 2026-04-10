@file:Suppress("unused")
package android.util

/**
 * Android Base64 stub backed by java.util.Base64.
 * Many Tachiyomi extensions use android.util.Base64 for decoding image URLs,
 * protected chapter content, etc.
 */
object Base64 {
    const val DEFAULT = 0
    const val NO_PADDING = 1
    const val NO_WRAP = 2
    const val CRLF = 4
    const val URL_SAFE = 8

    @JvmStatic
    fun decode(str: String?, flags: Int): ByteArray {
        if (str == null) return ByteArray(0)
        return try {
            if (flags and URL_SAFE != 0) {
                java.util.Base64.getUrlDecoder().decode(str.trim())
            } else {
                java.util.Base64.getDecoder().decode(str.trim())
            }
        } catch (e: Exception) {
            // Some extensions pass strings with whitespace/newlines
            try {
                java.util.Base64.getMimeDecoder().decode(str.trim())
            } catch (_: Exception) {
                ByteArray(0)
            }
        }
    }

    @JvmStatic
    fun decode(input: ByteArray, flags: Int): ByteArray {
        return decode(String(input), flags)
    }

    @JvmStatic
    fun encode(input: ByteArray?, flags: Int): ByteArray {
        if (input == null) return ByteArray(0)
        return if (flags and URL_SAFE != 0) {
            java.util.Base64.getUrlEncoder().let {
                if (flags and NO_PADDING != 0) it.withoutPadding() else it
            }.encode(input)
        } else {
            java.util.Base64.getEncoder().let {
                if (flags and NO_PADDING != 0) it.withoutPadding() else it
            }.encode(input)
        }
    }

    @JvmStatic
    fun encodeToString(input: ByteArray?, flags: Int): String {
        if (input == null) return ""
        return if (flags and URL_SAFE != 0) {
            java.util.Base64.getUrlEncoder().let {
                if (flags and NO_PADDING != 0) it.withoutPadding() else it
            }.encodeToString(input)
        } else {
            java.util.Base64.getEncoder().let {
                if (flags and NO_PADDING != 0) it.withoutPadding() else it
            }.encodeToString(input)
        }
    }
}
