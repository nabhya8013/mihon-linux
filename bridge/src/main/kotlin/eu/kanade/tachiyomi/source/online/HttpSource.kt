@file:Suppress("unused")
package eu.kanade.tachiyomi.source.online

import eu.kanade.tachiyomi.network.asObservable
import eu.kanade.tachiyomi.network.asObservableSuccess
import eu.kanade.tachiyomi.source.CatalogueSource
import eu.kanade.tachiyomi.source.model.*
import okhttp3.*
import rx.Observable
import java.security.MessageDigest

/**
 * Abstract HttpSource — the base class most Tachiyomi extensions extend.
 *
 * Provides OkHttp client, implements fetch methods by calling abstract
 * *Request() and *Parse() methods that extensions override.
 */
abstract class HttpSource : CatalogueSource {

    // ── Identity ─────────────────────────────────────────────────────────

    abstract val baseUrl: String

    override val id: Long by lazy {
        val key = "${name.lowercase()}/$lang/$versionId"
        val bytes = MessageDigest.getInstance("MD5").digest(key.toByteArray())
        var result = 0L
        for (i in 0 until 8) {
            result = result or ((bytes[i].toLong() and 0xff) shl (8 * i))
        }
        result
    }

    open val versionId: Int = 1

    // ── HTTP Client ──────────────────────────────────────────────────────

    open val network: eu.kanade.tachiyomi.network.NetworkHelper by lazy {
        eu.kanade.tachiyomi.network.NetworkHelper()
    }

    open val client: OkHttpClient by lazy {
        network.client
    }

    open val headers: Headers by lazy { headersBuilder().build() }

    protected open fun headersBuilder() = Headers.Builder().apply {
        add("User-Agent", DEFAULT_USER_AGENT)
    }

    // ── Popular ──────────────────────────────────────────────────────────

    override fun fetchPopularManga(page: Int): Observable<MangasPage> {
        return client.newCall(popularMangaRequest(page))
            .asObservableSuccess()
            .map { response -> popularMangaParse(response) }
    }

    protected abstract fun popularMangaRequest(page: Int): Request
    protected abstract fun popularMangaParse(response: Response): MangasPage

    // ── Latest ───────────────────────────────────────────────────────────

    override fun fetchLatestUpdates(page: Int): Observable<MangasPage> {
        return client.newCall(latestUpdatesRequest(page))
            .asObservableSuccess()
            .map { response -> latestUpdatesParse(response) }
    }

    protected abstract fun latestUpdatesRequest(page: Int): Request
    protected abstract fun latestUpdatesParse(response: Response): MangasPage

    // ── Search ───────────────────────────────────────────────────────────

    override fun fetchSearchManga(page: Int, query: String, filters: FilterList): Observable<MangasPage> {
        return client.newCall(searchMangaRequest(page, query, filters))
            .asObservableSuccess()
            .map { response -> searchMangaParse(response) }
    }

    protected abstract fun searchMangaRequest(page: Int, query: String, filters: FilterList): Request
    protected abstract fun searchMangaParse(response: Response): MangasPage

    // ── Manga Details ────────────────────────────────────────────────────

    override fun fetchMangaDetails(manga: SManga): Observable<SManga> {
        return client.newCall(mangaDetailsRequest(manga))
            .asObservableSuccess()
            .map { response ->
                mangaDetailsParse(response).apply { initialized = true }
            }
    }

    open fun mangaDetailsRequest(manga: SManga): Request {
        return Request.Builder()
            .url(baseUrl + manga.url)
            .headers(headers)
            .build()
    }

    protected abstract fun mangaDetailsParse(response: Response): SManga

    // ── Chapters ─────────────────────────────────────────────────────────

    override fun fetchChapterList(manga: SManga): Observable<List<SChapter>> {
        return client.newCall(chapterListRequest(manga))
            .asObservableSuccess()
            .map { response -> chapterListParse(response) }
    }

    open fun chapterListRequest(manga: SManga): Request {
        return Request.Builder()
            .url(baseUrl + manga.url)
            .headers(headers)
            .build()
    }

    protected abstract fun chapterListParse(response: Response): List<SChapter>

    // ── Pages ────────────────────────────────────────────────────────────

    override fun fetchPageList(chapter: SChapter): Observable<List<Page>> {
        return client.newCall(pageListRequest(chapter))
            .asObservableSuccess()
            .map { response -> pageListParse(response) }
    }

    open fun pageListRequest(chapter: SChapter): Request {
        return Request.Builder()
            .url(baseUrl + chapter.url)
            .headers(headers)
            .build()
    }

    protected abstract fun pageListParse(response: Response): List<Page>

    // ── Image ────────────────────────────────────────────────────────────

    /**
     * Parses the second-stage response for sources that serve a page URL first
     * and the image URL only after a follow-up request. Sources that need it
     * must override; the default is only reached when `getPageList` already
     * filled in `imageUrl`.
     */
    open fun imageUrlParse(response: Response): String =
        throw UnsupportedOperationException(
            "$name returned a page without an imageUrl but does not implement imageUrlParse()"
        )

    open fun imageUrlRequest(page: Page): Request {
        return Request.Builder()
            .url(baseUrl + page.url)
            .headers(headers)
            .build()
    }

    open fun fetchImageUrl(page: Page): Observable<String> {
        return client.newCall(imageUrlRequest(page))
            .asObservableSuccess()
            .map { imageUrlParse(it) }
    }

    open suspend fun getImageUrl(page: Page): String =
        fetchImageUrl(page).toBlocking().first()

    open fun imageRequest(page: Page): Request {
        return Request.Builder()
            .url(page.imageUrl ?: page.url)
            .headers(headers)
            .build()
    }

    open fun fetchImage(page: Page): Observable<Response> {
        return client.newCall(imageRequest(page)).asObservableSuccess()
    }

    open suspend fun getImage(page: Page): Response =
        fetchImage(page).toBlocking().first()

    /**
     * Combined details + chapter fetch used by newer extensions-lib sources.
     *
     * Sources built against the new API override this and implement neither
     * `chapterListParse` nor `getChapterList`; sources built against the old API
     * do the reverse, which is what this default covers.
     */
    open suspend fun getMangaUpdate(
        manga: SManga,
        currentChapters: List<SChapter>,
        fetchManga: Boolean,
        fetchChapters: Boolean,
    ): SMangaUpdate = SMangaUpdate(
        manga = if (fetchManga) getMangaDetails(manga) else null,
        chapters = if (fetchChapters) getChapterList(manga) else null,
    )

    /** Absolute, shareable URLs — used by "open in browser". */
    open fun getMangaUrl(manga: SManga): String = baseUrl + manga.url

    open fun getChapterUrl(chapter: SChapter): String = baseUrl + chapter.url

    /**
     * Stores a relative URL (which can later be used to rebuild the absolute URL).
     */
    fun SManga.setUrlWithoutDomain(url: String) {
        this.url = getUrlWithoutDomain(url)
    }

    fun SChapter.setUrlWithoutDomain(url: String) {
        this.url = getUrlWithoutDomain(url)
    }

    private fun getUrlWithoutDomain(orig: String): String {
        return orig.substringAfter(baseUrl)
    }

    companion object {
        const val DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    }
}
