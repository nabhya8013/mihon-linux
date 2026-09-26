package eu.kanade.tachiyomi.network

import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.ConcurrentHashMap
import kotlin.io.path.exists
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * Persistent CookieJar backed by the shared `MIHON_COOKIE_JAR` JSON file that the
 * Python side also reads and writes.
 *
 * Real Tachiyomi exposes this as `network.cookieJar`; extensions call
 * `cookieJar.get(url)` / `.remove(url)` directly, and OkHttp uses it for every
 * request so a challenge solved once in the WebKit window keeps working.
 */
class AndroidCookieJar : CookieJar {

    private val memory = ConcurrentHashMap<String, MutableMap<String, Cookie>>()
    private val json = Json { ignoreUnknownKeys = true; prettyPrint = true }
    private val jarPath: Path? = System.getenv("MIHON_COOKIE_JAR")
        ?.takeIf { it.isNotBlank() }
        ?.let { Path.of(it) }

    @Volatile
    private var loaded = false

    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        if (cookies.isEmpty()) return
        ensureLoaded()
        val bucket = memory.getOrPut(url.host.lowercase()) { ConcurrentHashMap() }
        for (cookie in cookies) {
            bucket[cookie.name] = cookie
        }
        persist()
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        ensureLoaded()
        val host = url.host.lowercase()
        val now = System.currentTimeMillis()
        return memory.entries
            .filter { (domain, _) -> host == domain || host.endsWith(".$domain") }
            .flatMap { it.value.values }
            .filter { it.expiresAt > now && it.matches(url) }
    }

    /** Extension-facing API: `network.cookieJar.get(url)`. */
    fun get(url: HttpUrl): List<Cookie> = loadForRequest(url)

    fun get(url: String): List<Cookie> =
        url.toHttpUrlOrNull()?.let { loadForRequest(it) } ?: emptyList()

    fun remove(url: HttpUrl, cookieNames: List<String>? = null, maxAge: Int = -1): Int {
        ensureLoaded()
        val bucket = memory[url.host.lowercase()] ?: return 0
        val removed = if (cookieNames == null) {
            val n = bucket.size
            bucket.clear()
            n
        } else {
            cookieNames.count { bucket.remove(it) != null }
        }
        if (removed > 0) persist()
        return removed
    }

    fun removeAll() {
        memory.clear()
        persist()
    }

    fun addAll(url: HttpUrl, cookies: List<Cookie>) = saveFromResponse(url, cookies)

    // ── Shared-jar persistence ───────────────────────────────────────────

    @Synchronized
    private fun ensureLoaded() {
        if (loaded) return
        loaded = true
        val path = jarPath ?: return
        if (!path.exists()) return
        runCatching {
            val root = json.parseToJsonElement(Files.readString(path)).jsonObject
            val records = root["cookies"]?.jsonArray ?: return@runCatching
            for (element in records) {
                val obj = element.jsonObject
                val domain = obj.str("domain")?.lowercase() ?: continue
                val name = obj.str("name") ?: continue
                val value = obj.str("value") ?: continue
                val secure = obj["secure"]?.jsonPrimitive?.content?.toBooleanStrictOrNull() ?: false
                val builder = Cookie.Builder()
                    .name(name)
                    .value(value)
                    .domain(domain)
                    .path(obj.str("path") ?: "/")
                if (secure) builder.secure()
                val cookie = builder.build()
                memory.getOrPut(domain) { ConcurrentHashMap() }[name] = cookie
            }
        }.onFailure {
            System.err.println("[AndroidCookieJar] Could not read shared jar: ${it.message}")
        }
    }

    @Synchronized
    private fun persist() {
        val path = jarPath ?: return
        runCatching {
            // Preserve every other section of the shared file (user_agents, ...).
            val existing: JsonObject = if (path.exists()) {
                json.parseToJsonElement(Files.readString(path)).jsonObject
            } else {
                JsonObject(emptyMap())
            }

            val cookieArray = buildJsonArray {
                for ((domain, bucket) in memory) {
                    for (cookie in bucket.values) {
                        add(buildJsonObject {
                            put("name", JsonPrimitive(cookie.name))
                            put("value", JsonPrimitive(cookie.value))
                            put("domain", JsonPrimitive(domain))
                            put("path", JsonPrimitive(cookie.path))
                            put("secure", JsonPrimitive(cookie.secure))
                        })
                    }
                }
            }

            val merged = buildJsonObject {
                for ((key, value) in existing) {
                    if (key != "cookies") put(key, value)
                }
                put("cookies", cookieArray)
            }

            Files.writeString(path, json.encodeToString(JsonObject.serializer(), merged))
        }.onFailure {
            System.err.println("[AndroidCookieJar] Could not write shared jar: ${it.message}")
        }
    }

    private fun JsonObject.str(key: String): String? =
        this[key]?.jsonPrimitive?.contentOrNullSafe()

    private fun JsonPrimitive.contentOrNullSafe(): String? =
        if (this.content == "null") null else this.content
}
