@file:Suppress("unused")
package eu.kanade.tachiyomi.source.online

import eu.kanade.tachiyomi.network.asJsoup
import eu.kanade.tachiyomi.source.model.*
import okhttp3.Response
import org.jsoup.nodes.Document
import org.jsoup.nodes.Element

/**
 * Abstract ParsedHttpSource — for extensions that scrape HTML pages with Jsoup.
 *
 * Instead of overriding *Parse(response), extensions override CSS selectors
 * and per-element extraction methods.
 */
abstract class ParsedHttpSource : HttpSource() {

    // ── Popular ──────────────────────────────────────────────────────────

    override fun popularMangaParse(response: Response): MangasPage {
        val document = response.asJsoup()
        val mangas = document.select(popularMangaSelector()).map { element ->
            popularMangaFromElement(element)
        }
        val hasNextPage = popularMangaNextPageSelector()?.let { selector ->
            document.selectFirst(selector) != null
        } ?: false
        return MangasPage(mangas, hasNextPage)
    }

    protected abstract fun popularMangaSelector(): String
    protected abstract fun popularMangaFromElement(element: Element): SManga
    protected abstract fun popularMangaNextPageSelector(): String?

    // ── Latest ───────────────────────────────────────────────────────────

    override fun latestUpdatesParse(response: Response): MangasPage {
        val document = response.asJsoup()
        val mangas = document.select(latestUpdatesSelector()).map { element ->
            latestUpdatesFromElement(element)
        }
        val hasNextPage = latestUpdatesNextPageSelector()?.let { selector ->
            document.selectFirst(selector) != null
        } ?: false
        return MangasPage(mangas, hasNextPage)
    }

    protected abstract fun latestUpdatesSelector(): String
    protected abstract fun latestUpdatesFromElement(element: Element): SManga
    protected abstract fun latestUpdatesNextPageSelector(): String?

    // ── Search ───────────────────────────────────────────────────────────

    override fun searchMangaParse(response: Response): MangasPage {
        val document = response.asJsoup()
        val mangas = document.select(searchMangaSelector()).map { element ->
            searchMangaFromElement(element)
        }
        val hasNextPage = searchMangaNextPageSelector()?.let { selector ->
            document.selectFirst(selector) != null
        } ?: false
        return MangasPage(mangas, hasNextPage)
    }

    protected abstract fun searchMangaSelector(): String
    protected abstract fun searchMangaFromElement(element: Element): SManga
    protected abstract fun searchMangaNextPageSelector(): String?

    // ── Manga Details ────────────────────────────────────────────────────

    override fun mangaDetailsParse(response: Response): SManga {
        return mangaDetailsParse(response.asJsoup())
    }

    protected abstract fun mangaDetailsParse(document: Document): SManga

    // ── Chapters ─────────────────────────────────────────────────────────

    override fun chapterListParse(response: Response): List<SChapter> {
        val document = response.asJsoup()
        return document.select(chapterListSelector()).map { element ->
            chapterFromElement(element)
        }
    }

    protected abstract fun chapterListSelector(): String
    protected abstract fun chapterFromElement(element: Element): SChapter

    // ── Pages ────────────────────────────────────────────────────────────

    override fun pageListParse(response: Response): List<Page> {
        return pageListParse(response.asJsoup())
    }

    protected abstract fun pageListParse(document: Document): List<Page>

    override fun imageUrlParse(response: Response): String {
        return imageUrlParse(response.asJsoup())
    }

    protected open fun imageUrlParse(document: Document): String = ""
}
