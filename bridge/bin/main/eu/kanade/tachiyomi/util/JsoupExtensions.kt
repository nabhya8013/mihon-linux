package eu.kanade.tachiyomi.util

import org.jsoup.nodes.Document
import org.jsoup.nodes.Element
import org.jsoup.nodes.Node
import org.jsoup.nodes.TextNode
import org.jsoup.select.Elements

import org.jsoup.Jsoup
import okhttp3.Response

/**
 * Jsoup extension functions commonly used by Tachiyomi extensions.
 * Original: eu.kanade.tachiyomi.util.JsoupExtensions
 */

/**
 * Parse an OkHttp Response body as a Jsoup Document.
 */
fun Response.asJsoup(html: String? = null): Document {
    return Jsoup.parse(html ?: body?.string() ?: "", request.url.toString())
}

/**
 * Returns the value of the first matched CSS query, or null.
 * Many extensions rely on this null-safe variant.
 */
fun Element.selectText(css: String, default: String? = null): String? {
    return selectFirst(css)?.text() ?: default
}

/**
 * Get text while preserving newlines from <br> and block elements.
 */
fun Element.textWithNewlines(): String {
    val buffer = StringBuilder()
    for (node in childNodes()) {
        when (node) {
            is TextNode -> buffer.append(node.text())
            is Element -> {
                if (node.tagName() in listOf("br", "p", "div")) {
                    buffer.append("\n")
                }
                buffer.append(node.textWithNewlines())
            }
        }
    }
    return buffer.toString().trim()
}

/**
 * Returns image URL from an element, checking common attributes.
 */
fun Element.imgAttr(): String {
    return when {
        hasAttr("data-lazy-src") -> attr("abs:data-lazy-src")
        hasAttr("data-src") -> attr("abs:data-src")
        hasAttr("data-cfsrc") -> attr("abs:data-cfsrc")
        hasAttr("srcset") -> attr("abs:srcset").substringBefore(" ")
        else -> attr("abs:src")
    }
}

/**
 * Returns image URL, alias used by some extensions.
 */
fun Element.getImgAttr(): String = imgAttr()

/**
 * Null-safe selectFirst that returns text or empty string.
 */
fun Element.selectFirstText(css: String): String {
    return selectFirst(css)?.text().orEmpty()
}

/**
 * Convenience: get attribute from first matched element.
 */
fun Element.selectFirstAttr(css: String, attr: String): String {
    return selectFirst(css)?.attr(attr).orEmpty()
}

/**
 * Extension to get ownText() cleanly.
 */
fun Element.ownTextTrimmed(): String = ownText().trim()
