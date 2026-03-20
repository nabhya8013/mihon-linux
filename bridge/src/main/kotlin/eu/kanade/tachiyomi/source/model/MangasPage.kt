package eu.kanade.tachiyomi.source.model

/**
 * Tachiyomi MangasPage — result container for browsing/search.
 */
data class MangasPage(
    val mangas: List<SManga>,
    val hasNextPage: Boolean,
)
