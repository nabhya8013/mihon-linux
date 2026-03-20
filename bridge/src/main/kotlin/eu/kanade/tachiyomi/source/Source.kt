package eu.kanade.tachiyomi.source

import eu.kanade.tachiyomi.source.model.*
import rx.Observable

/**
 * Base Source interface — every Tachiyomi source implements this.
 */
interface Source {
    val id: Long
    val name: String
    val lang: String

    // RxJava 1 API (older extensions)
    fun fetchMangaDetails(manga: SManga): Observable<SManga> =
        throw UnsupportedOperationException("Not implemented")

    fun fetchChapterList(manga: SManga): Observable<List<SChapter>> =
        throw UnsupportedOperationException("Not implemented")

    fun fetchPageList(chapter: SChapter): Observable<List<Page>> =
        throw UnsupportedOperationException("Not implemented")

    // Suspend API (newer extensions — Mihon era)
    suspend fun getMangaDetails(manga: SManga): SManga =
        fetchMangaDetails(manga).toBlocking().first()

    suspend fun getChapterList(manga: SManga): List<SChapter> =
        fetchChapterList(manga).toBlocking().first()

    suspend fun getPageList(chapter: SChapter): List<Page> =
        fetchPageList(chapter).toBlocking().first()
}

/**
 * CatalogueSource — adds browsing and search.
 */
interface CatalogueSource : Source {
    val supportsLatest: Boolean

    // RxJava 1 API
    fun fetchPopularManga(page: Int): Observable<MangasPage> =
        throw UnsupportedOperationException("Not implemented")

    fun fetchSearchManga(page: Int, query: String, filters: FilterList): Observable<MangasPage> =
        throw UnsupportedOperationException("Not implemented")

    fun fetchLatestUpdates(page: Int): Observable<MangasPage> =
        throw UnsupportedOperationException("Not implemented")

    // Suspend API
    suspend fun getPopularManga(page: Int): MangasPage =
        fetchPopularManga(page).toBlocking().first()

    suspend fun getSearchManga(page: Int, query: String, filters: FilterList): MangasPage =
        fetchSearchManga(page, query, filters).toBlocking().first()

    suspend fun getLatestUpdates(page: Int): MangasPage =
        fetchLatestUpdates(page).toBlocking().first()

    fun getFilterList(): FilterList = FilterList()
}
