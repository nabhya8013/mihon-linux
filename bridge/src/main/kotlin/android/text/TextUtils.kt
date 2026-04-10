@file:Suppress("unused")
package android.text

/**
 * Minimal TextUtils stub — commonly referenced by Tachiyomi extensions.
 */
object TextUtils {
    @JvmStatic
    fun isEmpty(str: CharSequence?): Boolean = str.isNullOrEmpty()

    @JvmStatic
    fun join(delimiter: CharSequence, tokens: Iterable<*>): String =
        tokens.joinToString(delimiter)

    @JvmStatic
    fun join(delimiter: CharSequence, tokens: Array<out Any?>): String =
        tokens.joinToString(delimiter)

    @JvmStatic
    fun equals(a: CharSequence?, b: CharSequence?): Boolean = a.toString() == b.toString()

    @JvmStatic
    fun htmlEncode(s: String): String =
        s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\"", "&quot;")
            .replace("'", "&#39;")
}
