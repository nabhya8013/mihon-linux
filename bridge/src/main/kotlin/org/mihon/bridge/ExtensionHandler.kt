package org.mihon.bridge

import eu.kanade.tachiyomi.source.CatalogueSource
import eu.kanade.tachiyomi.source.Source
import eu.kanade.tachiyomi.source.model.*
import eu.kanade.tachiyomi.source.online.HttpSource
import kotlinx.serialization.json.*

/**
 * Handles extension.* JSON-RPC methods — loading extensions, fetching manga, etc.
 */
object ExtensionHandler {

    fun handle(method: String, params: JsonObject): JsonElement {
        return when (method) {
            "extension.load" -> handleLoad(params)
            "extension.list" -> handleList()
            "extension.unload" -> handleUnload()
            "extension.popular" -> handlePopular(params)
            "extension.latest" -> handleLatest(params)
            "extension.search" -> handleSearch(params)
            "extension.details" -> handleDetails(params)
            "extension.chapters" -> handleChapters(params)
            "extension.pages" -> handlePages(params)
            "extension.filters" -> handleFilters(params)
            else -> throw NoSuchMethodException(method)
        }
    }

    // ── extension.load ───────────────────────────────────────────────────
    // params: { jarPath: String, classNames: String }

    private fun handleLoad(params: JsonObject): JsonElement {
        val jarPath = params["jarPath"]?.jsonPrimitive?.content
            ?: throw IllegalArgumentException("Missing 'jarPath' parameter")
        val classNames = params["classNames"]?.jsonPrimitive?.content
            ?: throw IllegalArgumentException("Missing 'classNames' parameter")

        val sources = ExtensionLoader.loadExtension(jarPath, classNames)

        return buildJsonObject {
            put("loaded", sources.size)
            put("sources", buildJsonArray {
                for (src in sources) {
                    add(sourceToInfo(src))
                }
            })
        }
    }

    // ── extension.list ───────────────────────────────────────────────────

    private fun handleList(): JsonElement {
        val sources = ExtensionLoader.getAllSources()
        return buildJsonArray {
            for (src in sources) {
                add(sourceToInfo(src))
            }
        }
    }

    // ── extension.unload ─────────────────────────────────────────────────

    private fun handleUnload(): JsonElement {
        ExtensionLoader.unloadAll()
        return buildJsonObject { put("unloaded", true) }
    }

    // ── extension.popular ────────────────────────────────────────────────
    // params: { extensionId: Long, page: Int }

    private fun handlePopular(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val page = params["page"]?.jsonPrimitive?.int ?: 1

        val result = source.fetchPopularManga(page).toBlocking().first()
        return bridgeJson.encodeToJsonElement(result.toBridge())
    }

    // ── extension.latest ─────────────────────────────────────────────────

    private fun handleLatest(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val page = params["page"]?.jsonPrimitive?.int ?: 1

        val result = source.fetchLatestUpdates(page).toBlocking().first()
        return bridgeJson.encodeToJsonElement(result.toBridge())
    }

    // ── extension.search ─────────────────────────────────────────────────
    // params: { extensionId: Long, page: Int, query: String }

    private fun handleSearch(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val page = params["page"]?.jsonPrimitive?.int ?: 1
        val query = params["query"]?.jsonPrimitive?.content ?: ""

        // For now, use empty filter list. Phase 2 can add filter passing.
        val result = source.fetchSearchManga(page, query, FilterList()).toBlocking().first()
        return bridgeJson.encodeToJsonElement(result.toBridge())
    }

    // ── extension.details ────────────────────────────────────────────────
    // params: { extensionId: Long, mangaUrl: String }

    private fun handleDetails(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        
        val manga = if (params.containsKey("manga")) {
            bridgeJson.decodeFromJsonElement<BridgeManga>(params["manga"]!!).toSManga()
        } else {
            val mangaUrl = params["mangaUrl"]?.jsonPrimitive?.content
                ?: throw IllegalArgumentException("Missing 'mangaUrl'")
            SManga.create().apply { url = mangaUrl }
        }

        System.err.println("[ExtensionHandler] fetchMangaDetails for: ${manga.url}")
        val result = source.fetchMangaDetails(manga).toBlocking().first()
        return bridgeJson.encodeToJsonElement(result.toBridge())
    }

    // ── extension.chapters ───────────────────────────────────────────────
    // params: { extensionId: Long, mangaUrl: String }

    private fun handleChapters(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)

        val manga = if (params.containsKey("manga")) {
            bridgeJson.decodeFromJsonElement<BridgeManga>(params["manga"]!!).toSManga()
        } else {
            val mangaUrl = params["mangaUrl"]?.jsonPrimitive?.content
                ?: throw IllegalArgumentException("Missing 'mangaUrl'")
            SManga.create().apply { url = mangaUrl }
        }

        System.err.println("[ExtensionHandler] fetchChapterList for: ${manga.url}")
        val chapters = source.fetchChapterList(manga).toBlocking().first()
        System.err.println("[ExtensionHandler] Got ${chapters.size} chapters")

        return buildJsonArray {
            for (ch in chapters) {
                add(bridgeJson.encodeToJsonElement(ch.toBridge()))
            }
        }
    }

    // ── extension.pages ──────────────────────────────────────────────────
    // params: { extensionId: Long, chapterUrl: String }

    private fun handlePages(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val chapterUrl = params["chapterUrl"]?.jsonPrimitive?.content
            ?: throw IllegalArgumentException("Missing 'chapterUrl'")

        System.err.println("[ExtensionHandler] fetchPageList for: $chapterUrl")
        val chapter = SChapter.create().apply { url = chapterUrl }
        val pages = source.fetchPageList(chapter).toBlocking().first()
        System.err.println("[ExtensionHandler] Got ${pages.size} pages")

        return buildJsonArray {
            for (page in pages) {
                add(bridgeJson.encodeToJsonElement(page.toBridge()))
            }
        }
    }

    // ── extension.filters ────────────────────────────────────────────────
    // params: { extensionId: Long }

    private fun handleFilters(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val filters = source.getFilterList()

        return buildJsonArray {
            for (filter in filters) {
                add(buildJsonObject {
                    put("name", filter.name)
                    put("type", filter::class.simpleName ?: "Unknown")
                    put("state", filter.state.toString())
                })
            }
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────────

    private fun requireSource(params: JsonObject): Source {
        val extId = params["extensionId"]?.jsonPrimitive?.long
            ?: throw IllegalArgumentException("Missing 'extensionId'")
        return ExtensionLoader.getSource(extId)
            ?: throw IllegalArgumentException("Extension not loaded: $extId")
    }

    private fun requireCatalogueSource(params: JsonObject): CatalogueSource {
        val source = requireSource(params)
        return source as? CatalogueSource
            ?: throw IllegalArgumentException("Extension ${source.id} (${source.name}) is not a CatalogueSource")
    }

    private fun sourceToInfo(src: Source): JsonObject {
        return buildJsonObject {
            put("id", src.id)
            put("name", src.name)
            put("lang", src.lang)
            if (src is HttpSource) {
                put("baseUrl", src.baseUrl)
            }
            if (src is CatalogueSource) {
                put("supportsLatest", src.supportsLatest)
            }
        }
    }
}
