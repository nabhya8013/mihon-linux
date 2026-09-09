package eu.kanade.tachiyomi.source.model

/**
 * Combined result of the newer `HttpSource.getMangaUpdate()` API.
 *
 * Recent extensions-lib versions replaced the separate details/chapters calls
 * with a single round trip that returns both, so sources built against it
 * implement `getMangaUpdate` and leave `chapterListParse` unimplemented.
 * Calling the old path on those sources fails with AbstractMethodError.
 */
class SMangaUpdate(
    val manga: SManga? = null,
    val chapters: List<SChapter>? = null,
)
