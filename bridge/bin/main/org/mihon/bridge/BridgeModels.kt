package org.mihon.bridge

import eu.kanade.tachiyomi.source.model.*
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*

/**
 * Wire-format models for serializing Tachiyomi data across the JSON-RPC bridge.
 * These are separate from the Tachiyomi models to decouple the wire format.
 */

@Serializable
data class BridgeManga(
    val url: String = "",
    val title: String = "",
    val artist: String? = null,
    val author: String? = null,
    val description: String? = null,
    val genre: String? = null,
    val status: Int = 0,
    val thumbnailUrl: String? = null,
    val initialized: Boolean = false,
)

@Serializable
data class BridgeChapter(
    val url: String = "",
    val name: String = "",
    val dateUpload: Long = 0,
    val chapterNumber: Float = -1f,
    val scanlator: String? = null,
)

@Serializable
data class BridgePage(
    val index: Int = 0,
    val url: String = "",
    val imageUrl: String? = null,
)

@Serializable
data class BridgeMangasPage(
    val mangas: List<BridgeManga>,
    val hasNextPage: Boolean,
)

@Serializable
data class BridgeExtensionInfo(
    val id: Long = 0,
    val name: String = "",
    val lang: String = "",
    val baseUrl: String = "",
    val supportsLatest: Boolean = false,
)

// ── Converters ─────────────────────────────────────────────────────────

fun SManga.toBridge() = BridgeManga(
    url = url,
    title = title,
    artist = artist,
    author = author,
    description = description,
    genre = genre,
    status = status,
    thumbnailUrl = thumbnail_url,
    initialized = initialized,
)

fun SChapter.toBridge() = BridgeChapter(
    url = url,
    name = name,
    dateUpload = date_upload,
    chapterNumber = chapter_number,
    scanlator = scanlator,
)

fun Page.toBridge() = BridgePage(
    index = index,
    url = url,
    imageUrl = imageUrl ?: uri?.toString(),
)

fun MangasPage.toBridge() = BridgeMangasPage(
    mangas = mangas.map { it.toBridge() },
    hasNextPage = hasNextPage,
)

/**
 * Convert a BridgeManga back to SManga (for passing into extension methods).
 */
fun BridgeManga.toSManga(): SManga = SManga.create().apply {
    url = this@toSManga.url
    title = this@toSManga.title
    artist = this@toSManga.artist
    author = this@toSManga.author
    description = this@toSManga.description
    genre = this@toSManga.genre
    status = this@toSManga.status
    thumbnail_url = this@toSManga.thumbnailUrl
    initialized = this@toSManga.initialized
}

fun BridgeChapter.toSChapter(): SChapter = SChapter.create().apply {
    url = this@toSChapter.url
    name = this@toSChapter.name
    date_upload = this@toSChapter.dateUpload
    chapter_number = this@toSChapter.chapterNumber
    scanlator = this@toSChapter.scanlator
}

// ── JSON helpers ───────────────────────────────────────────────────────

val bridgeJson = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
    isLenient = true
}

inline fun <reified T> T.toJsonElement(): JsonElement = bridgeJson.encodeToJsonElement(this)
