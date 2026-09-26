package org.mihon.bridge

import android.util.Base64
import androidx.preference.*
import eu.kanade.tachiyomi.source.CatalogueSource
import eu.kanade.tachiyomi.source.ConfigurableSource
import eu.kanade.tachiyomi.source.Source
import eu.kanade.tachiyomi.source.model.*
import eu.kanade.tachiyomi.source.online.HttpSource
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import uy.kohesive.injekt.Injekt
import uy.kohesive.injekt.api.get

/**
 * Handles extension.* JSON-RPC methods.
 *
 * Dispatch always goes through the **suspend** source API (`getPopularManga`,
 * `getChapterList`, ...). Modern Mihon/Keiyoushi extensions override only those;
 * older Rx-era extensions inherit defaults that delegate back to `fetchX(...)`,
 * so this single path covers both generations. Calling `fetchX` directly — as an
 * earlier version did — made every suspend-only extension fail with
 * `UnsupportedOperationException: Not implemented`.
 */
object ExtensionHandler {

    fun handle(method: String, params: JsonObject): JsonElement {
        return when (method) {
            "extension.load" -> handleLoad(params)
            "extension.list" -> handleList()
            "extension.unload" -> handleUnload()
            "extension.unloadJar" -> handleUnloadJar(params)
            "extension.popular" -> handlePopular(params)
            "extension.latest" -> handleLatest(params)
            "extension.search" -> handleSearch(params)
            "extension.details" -> handleDetails(params)
            "extension.chapters" -> handleChapters(params)
            "extension.pages" -> handlePages(params)
            "extension.filters" -> handleFilters(params)
            "extension.image" -> handleImage(params)
            "extension.preferences" -> handlePreferences(params)
            "extension.setPreference" -> handleSetPreference(params)
            else -> throw NoSuchMethodException(method)
        }
    }

    // ── extension.load ───────────────────────────────────────────────────
    // params: { jarPath: String, classNames: String, nativeLibDir: String? }

    private fun handleLoad(params: JsonObject): JsonElement {
        val jarPath = params["jarPath"]?.jsonPrimitive?.content
            ?: throw IllegalArgumentException("Missing 'jarPath' parameter")
        val classNames = params["classNames"]?.jsonPrimitive?.content
            ?: throw IllegalArgumentException("Missing 'classNames' parameter")
        params["nativeLibDir"]?.jsonPrimitive?.contentOrNull?.let { registerNativeLibDir(it) }
        val nsfw = params["nsfw"]?.jsonPrimitive?.booleanOrNull ?: false

        val sources = ExtensionLoader.loadExtension(jarPath, classNames, nsfw)

        return buildJsonObject {
            put("loaded", sources.size)
            put("sources", buildJsonArray { sources.forEach { add(sourceToInfo(it)) } })
        }
    }

    /** Make bundled `.so` files visible to System.loadLibrary. */
    private fun registerNativeLibDir(dir: String) {
        runCatching {
            val current = System.getProperty("java.library.path") ?: ""
            if (!current.split(java.io.File.pathSeparator).contains(dir)) {
                System.setProperty(
                    "java.library.path",
                    if (current.isBlank()) dir else "$current${java.io.File.pathSeparator}$dir",
                )
            }
        }.onFailure {
            System.err.println("[ExtensionHandler] Could not register native lib dir: ${it.message}")
        }
    }

    private fun handleList(): JsonElement =
        buildJsonArray { ExtensionLoader.getAllSources().forEach { add(sourceToInfo(it)) } }

    private fun handleUnload(): JsonElement {
        ExtensionLoader.unloadAll()
        return buildJsonObject { put("unloaded", true) }
    }

    private fun handleUnloadJar(params: JsonObject): JsonElement {
        val jarPath = params["jarPath"]?.jsonPrimitive?.content
            ?: throw IllegalArgumentException("Missing 'jarPath' parameter")
        return buildJsonObject { put("unloaded", ExtensionLoader.unloadJar(jarPath)) }
    }

    // ── Browsing ─────────────────────────────────────────────────────────

    private fun handlePopular(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val page = params["page"]?.jsonPrimitive?.int ?: 1
        val result = runBlocking { source.getPopularManga(page) }
        return bridgeJson.encodeToJsonElement(result.toBridge())
    }

    private fun handleLatest(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val page = params["page"]?.jsonPrimitive?.int ?: 1
        val result = runBlocking { source.getLatestUpdates(page) }
        return bridgeJson.encodeToJsonElement(result.toBridge())
    }

    private fun handleSearch(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val page = params["page"]?.jsonPrimitive?.int ?: 1
        val query = params["query"]?.jsonPrimitive?.content ?: ""
        val filters = applyFilterState(source, params["filters"] as? JsonArray)
        val result = runBlocking { source.getSearchManga(page, query, filters) }
        return bridgeJson.encodeToJsonElement(result.toBridge())
    }

    private fun handleDetails(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val manga = mangaFromParams(params)
        val result = fetchDetails(source, manga)

        // Most sources fill in only the metadata and leave `url` untouched on
        // the object they return, so carry the requested URL across. Without
        // this the client loses the manga URL and every later chapter fetch
        // runs against an empty path.
        if (result.url.isBlank()) {
            result.url = manga.url
        }
        return bridgeJson.encodeToJsonElement(result.toBridge())
    }

    private fun handleChapters(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val manga = mangaFromParams(params)

        val chapters = try {
            fetchChapters(source, manga)
        } catch (e: Throwable) {
            System.err.println(
                "[ExtensionHandler] getChapterList failed for ${manga.url} " +
                    "(${source::class.qualifiedName}): ${e::class.simpleName}: ${e.message}"
            )
            e.printStackTrace(System.err)
            throw e
        }

        if (chapters.isEmpty()) {
            System.err.println(
                "[ExtensionHandler] Chapter list empty for ${manga.url} — " +
                    "site may need a Cloudflare/WebView solve."
            )
        }

        return buildJsonArray {
            chapters.forEach { add(bridgeJson.encodeToJsonElement(it.toBridge())) }
        }
    }

    private fun handlePages(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        val chapter = SChapter.create().apply {
            url = params["chapterUrl"]?.jsonPrimitive?.content
                ?: throw IllegalArgumentException("Missing 'chapterUrl'")
            params["chapterName"]?.jsonPrimitive?.contentOrNull?.let { name = it }
        }

        val pages = runBlocking { source.getPageList(chapter) }

        // Sources that resolve the image URL in a second request leave imageUrl
        // null; resolve it here so the client always receives a usable URL.
        val httpSource = source as? HttpSource
        val resolved = pages.map { page ->
            if (page.imageUrl.isNullOrBlank() && httpSource != null && page.url.isNotBlank()) {
                runCatching { runBlocking { httpSource.getImageUrl(page) } }
                    .onFailure {
                        System.err.println(
                            "[ExtensionHandler] getImageUrl failed for ${page.url}: ${it.message}"
                        )
                    }
                    .getOrNull()
                    ?.let { url -> page.also { it.imageUrl = url } }
                    ?: page
            } else {
                page
            }
        }

        return buildJsonArray {
            resolved.forEach { add(bridgeJson.encodeToJsonElement(it.toBridge())) }
        }
    }

    // ── extension.image ──────────────────────────────────────────────────
    // params: { extensionId, imageUrl, pageUrl? }
    //
    // Fetches through the source's own OkHttp client so per-source headers,
    // referers, rate limiters and the shared Cloudflare cookie jar all apply —
    // none of which the Python side can reproduce on its own.

    private fun handleImage(params: JsonObject): JsonElement {
        val source = requireSource(params) as? HttpSource
            ?: throw IllegalArgumentException("Source does not support image fetching")
        val imageUrl = params["imageUrl"]?.jsonPrimitive?.content
            ?: throw IllegalArgumentException("Missing 'imageUrl'")

        val page = Page(
            index = params["index"]?.jsonPrimitive?.intOrNull ?: 0,
            url = params["pageUrl"]?.jsonPrimitive?.contentOrNull ?: "",
            imageUrl = imageUrl,
        )

        source.client.newCall(source.imageRequest(page)).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("HTTP ${response.code} fetching $imageUrl")
            }
            val body = response.body ?: throw IllegalStateException("Empty body for $imageUrl")
            val bytes = body.bytes()
            return buildJsonObject {
                put("contentType", response.header("Content-Type") ?: "image/jpeg")
                put("size", bytes.size)
                put("data", Base64.encodeToString(bytes, Base64.NO_WRAP))
            }
        }
    }

    // ── Filters ──────────────────────────────────────────────────────────

    private fun handleFilters(params: JsonObject): JsonElement {
        val source = requireCatalogueSource(params)
        return buildJsonArray {
            source.getFilterList().forEachIndexed { index, filter ->
                add(serializeFilter(filter, index))
            }
        }
    }

    /** Full filter serialisation — enough for the client to render real widgets. */
    private fun serializeFilter(filter: Filter<*>, index: Int): JsonObject = buildJsonObject {
        put("index", index)
        put("name", filter.name)
        put("type", filterType(filter))
        when (filter) {
            is Filter.Select<*> -> {
                put("values", buildJsonArray { filter.values.forEach { add(it.toString()) } })
                put("state", filter.state)
            }
            is Filter.Sort -> {
                put("values", buildJsonArray { filter.values.forEach { add(it) } })
                val selection = filter.state
                if (selection == null) {
                    put("state", JsonNull)
                } else {
                    put("state", buildJsonObject {
                        put("index", selection.index)
                        put("ascending", selection.ascending)
                    })
                }
            }
            is Filter.Group<*> -> {
                put("state", buildJsonArray {
                    filter.state.forEachIndexed { childIndex, child ->
                        if (child is Filter<*>) {
                            add(serializeFilter(child, childIndex))
                        } else {
                            add(JsonPrimitive(child.toString()))
                        }
                    }
                })
            }
            is Filter.TriState -> put("state", filter.state)
            is Filter.CheckBox -> put("state", filter.state)
            is Filter.Text -> put("state", filter.state)
            else -> put("state", JsonNull)
        }
    }

    private fun filterType(filter: Filter<*>): String = when (filter) {
        is Filter.Header -> "header"
        is Filter.Separator -> "separator"
        is Filter.Select<*> -> "select"
        is Filter.Text -> "text"
        is Filter.CheckBox -> "checkbox"
        is Filter.TriState -> "tristate"
        is Filter.Group<*> -> "group"
        is Filter.Sort -> "sort"
        else -> filter::class.simpleName?.lowercase() ?: "unknown"
    }

    /**
     * Rebuild the source's FilterList and apply client-supplied state to it.
     * Filters are matched positionally, mirroring how Android passes them back.
     */
    @Suppress("UNCHECKED_CAST")
    private fun applyFilterState(source: CatalogueSource, states: JsonArray?): FilterList {
        val filters = source.getFilterList()
        if (states.isNullOrEmpty()) return filters

        fun apply(filter: Filter<*>, node: JsonObject) {
            val state = node["state"] ?: return
            when (filter) {
                is Filter.Select<*> ->
                    state.jsonPrimitive.intOrNull?.let { (filter as Filter<Int>).state = it }
                is Filter.TriState ->
                    state.jsonPrimitive.intOrNull?.let { (filter as Filter<Int>).state = it }
                is Filter.CheckBox ->
                    state.jsonPrimitive.booleanOrNull?.let { (filter as Filter<Boolean>).state = it }
                is Filter.Text ->
                    (filter as Filter<String>).state = state.jsonPrimitive.content
                is Filter.Sort -> {
                    val obj = state as? JsonObject ?: return
                    val idx = obj["index"]?.jsonPrimitive?.intOrNull ?: return
                    val asc = obj["ascending"]?.jsonPrimitive?.booleanOrNull ?: true
                    (filter as Filter<Filter.Sort.Selection?>).state =
                        Filter.Sort.Selection(idx, asc)
                }
                is Filter.Group<*> -> {
                    val children = state as? JsonArray ?: return
                    filter.state.forEachIndexed { i, child ->
                        val childNode = children.getOrNull(i) as? JsonObject ?: return@forEachIndexed
                        if (child is Filter<*>) apply(child, childNode)
                    }
                }
                else -> Unit
            }
        }

        states.forEach { element ->
            val node = element as? JsonObject ?: return@forEach
            val index = node["index"]?.jsonPrimitive?.intOrNull ?: return@forEach
            filters.getOrNull(index)?.let { apply(it, node) }
        }
        return filters
    }

    // ── Per-source preferences ───────────────────────────────────────────

    private fun handlePreferences(params: JsonObject): JsonElement {
        val source = requireSource(params)
        val configurable = source as? ConfigurableSource
            ?: return buildJsonArray { }

        val context = Injekt.get<android.app.Application>()
        val screen = PreferenceScreen(context)
        runCatching { configurable.setupPreferenceScreen(screen) }
            .onFailure {
                System.err.println(
                    "[ExtensionHandler] setupPreferenceScreen failed for ${source.name}: " +
                        "${it::class.simpleName}: ${it.message}"
                )
                it.printStackTrace(System.err)
                return buildJsonArray { }
            }
        System.err.println(
            "[ExtensionHandler] ${source.name}: ${screen.preferenceCount} preference(s) declared"
        )

        val prefs = sourcePreferences(source)
        return buildJsonArray {
            screen.getPreferences().forEach { add(serializePreference(it, prefs)) }
        }
    }

    private fun handleSetPreference(params: JsonObject): JsonElement {
        val source = requireSource(params)
        val key = params["key"]?.jsonPrimitive?.content
            ?: throw IllegalArgumentException("Missing 'key'")
        val value = params["value"] ?: throw IllegalArgumentException("Missing 'value'")

        val editor = sourcePreferences(source).edit()
        when {
            value is JsonArray ->
                editor.putStringSet(key, value.map { it.jsonPrimitive.content }.toSet())
            value.jsonPrimitive.booleanOrNull != null ->
                editor.putBoolean(key, value.jsonPrimitive.boolean)
            value.jsonPrimitive.intOrNull != null ->
                editor.putInt(key, value.jsonPrimitive.int)
            else -> editor.putString(key, value.jsonPrimitive.content)
        }
        editor.apply()

        return buildJsonObject {
            put("saved", true)
            put("key", key)
        }
    }

    private fun sourcePreferences(source: Source): android.content.SharedPreferences =
        Injekt.get<android.app.Application>()
            .getSharedPreferences("source_${source.id}", android.content.Context.MODE_PRIVATE)

    private fun serializePreference(
        pref: Preference,
        prefs: android.content.SharedPreferences,
    ): JsonObject = buildJsonObject {
        put("key", pref.key)
        put("type", pref.widgetType)
        put("title", pref.title?.toString() ?: "")
        put("summary", pref.summary?.toString() ?: "")
        put("enabled", pref.isEnabled)
        when (pref) {
            is ListPreference -> {
                put("entries", buildJsonArray { pref.entries.forEach { add(it.toString()) } })
                put("entryValues", buildJsonArray { pref.entryValues.forEach { add(it.toString()) } })
                put("value", prefs.getString(pref.key, pref.storedDefault as? String ?: "") ?: "")
            }
            is MultiSelectListPreference -> {
                put("entries", buildJsonArray { pref.entries.forEach { add(it.toString()) } })
                put("entryValues", buildJsonArray { pref.entryValues.forEach { add(it.toString()) } })
                @Suppress("UNCHECKED_CAST")
                val fallback = pref.storedDefault as? Set<String> ?: emptySet()
                put("value", buildJsonArray {
                    (prefs.getStringSet(pref.key, fallback) ?: fallback).forEach { add(it) }
                })
            }
            is TwoStatePreference ->
                put("value", prefs.getBoolean(pref.key, pref.storedDefault as? Boolean ?: false))
            is EditTextPreference ->
                put("value", prefs.getString(pref.key, pref.storedDefault as? String ?: "") ?: "")
            is PreferenceGroup ->
                put("children", buildJsonArray {
                    pref.getPreferences().forEach { add(serializePreference(it, prefs)) }
                })
            else -> put("value", JsonNull)
        }
    }

    // ── Dispatch across the old and new source APIs ──────────────────────
    //
    // Sources built against recent extensions-lib implement the combined
    // `getMangaUpdate()` and leave `chapterListParse`/`getChapterList`
    // unimplemented; older sources do the opposite. Try the new API first and
    // fall back when the source does not implement it.

    private fun fetchDetails(source: CatalogueSource, manga: SManga): SManga {
        (source as? HttpSource)?.let { http ->
            tryNewApi { runBlocking { http.getMangaUpdate(manga, emptyList(), true, false) }.manga }
                ?.let { return it }
        }
        return runBlocking { source.getMangaDetails(manga) }
    }

    private fun fetchChapters(source: CatalogueSource, manga: SManga): List<SChapter> {
        (source as? HttpSource)?.let { http ->
            tryNewApi { runBlocking { http.getMangaUpdate(manga, emptyList(), false, true) }.chapters }
                ?.let { return it }
        }
        return runBlocking { source.getChapterList(manga) }
    }

    /**
     * Run a new-API call, returning null only when the source genuinely does
     * not implement it.
     *
     * Real failures (HTTP errors, parse errors) are rethrown rather than
     * swallowed — retrying them on the legacy path just produces a second,
     * more confusing error and hides the actual cause.
     */
    private fun <T : Any> tryNewApi(block: () -> T?): T? = try {
        block()
    } catch (e: AbstractMethodError) {
        null
    } catch (e: NoSuchMethodError) {
        null
    } catch (e: NotImplementedError) {
        null
    } catch (e: UnsupportedOperationException) {
        null
    }

    // ── Helpers ──────────────────────────────────────────────────────────

    private fun mangaFromParams(params: JsonObject): SManga =
        if (params.containsKey("manga")) {
            bridgeJson.decodeFromJsonElement<BridgeManga>(params["manga"]!!).toSManga()
        } else {
            val mangaUrl = params["mangaUrl"]?.jsonPrimitive?.content
                ?: throw IllegalArgumentException("Missing 'mangaUrl'")
            SManga.create().apply { url = mangaUrl }
        }

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

    private fun sourceToInfo(src: Source): JsonObject = buildJsonObject {
        put("id", src.id)
        put("name", src.name)
        put("lang", src.lang)
        if (src is HttpSource) put("baseUrl", src.baseUrl)
        if (src is CatalogueSource) put("supportsLatest", src.supportsLatest)
        put("isConfigurable", src is ConfigurableSource)
        put("nsfw", ExtensionLoader.isNsfw(src.id))
    }
}
