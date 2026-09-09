@file:Suppress("unused")
package android.text

import org.jsoup.Jsoup
import org.jsoup.nodes.Document
import org.jsoup.parser.Parser

/**
 * android.text.Html stub backed by jsoup.
 *
 * Extensions use `Html.fromHtml(description)` to strip markup out of synopsis
 * fields. Returns a plain String (which satisfies the CharSequence contract
 * callers actually rely on).
 */
object Html {
    const val FROM_HTML_MODE_LEGACY = 0
    const val FROM_HTML_MODE_COMPACT = 63

    @JvmStatic
    fun fromHtml(source: String?): CharSequence = fromHtml(source, FROM_HTML_MODE_LEGACY)

    @JvmStatic
    fun fromHtml(source: String?, flags: Int): CharSequence {
        if (source.isNullOrEmpty()) return ""
        val doc = Jsoup.parse(source)
        doc.outputSettings(Document.OutputSettings().prettyPrint(false))
        doc.select("br").before("\\n")
        doc.select("p").before("\\n")
        val text = doc.body().html()
            .replace("\\\\n", "\n")
        return Parser.unescapeEntities(Jsoup.parse(text).text(), false)
    }

    @JvmStatic
    fun escapeHtml(text: CharSequence?): String =
        if (text == null) "" else TextUtils.htmlEncode(text.toString())
}
