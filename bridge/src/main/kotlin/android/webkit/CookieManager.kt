@file:Suppress("unused")
package android.webkit

import java.net.URI
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.exists
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/**
 * Stub CookieManager for desktop JVM.
 * Some extensions use CookieManager to persist/read cookies from WebView.
 * On desktop we back this with the shared mihon-linux cookie jar when present.
 */
class CookieManager private constructor() {

    private val cookies = mutableMapOf<String, String>()
    private val json = Json {
        ignoreUnknownKeys = true
        prettyPrint = true
    }
    private val sharedJarPath: Path? = System.getenv("MIHON_COOKIE_JAR")
        ?.takeIf { it.isNotBlank() }
        ?.let { Path.of(it) }

    fun getCookie(url: String): String? {
        loadFromDisk()
        return cookies[url] ?: cookieHeaderForUrl(url)
    }

    fun setCookie(url: String, value: String) {
        cookies[url] = value
        saveCookie(url, value)
    }

    fun removeAllCookies(callback: ((Boolean) -> Unit)?) {
        cookies.clear()
        saveRecords(emptyList())
        callback?.invoke(true)
    }

    fun flush() {
        loadFromDisk()
    }

    fun setAcceptCookie(accept: Boolean) {
        // No-op
    }

    fun hasCookies(): Boolean {
        loadFromDisk()
        return cookies.isNotEmpty() || loadRecords().isNotEmpty()
    }

    private fun loadFromDisk() {
        for (record in loadRecords()) {
            val url = if (record.secure) "https://${record.domain}" else "http://${record.domain}"
            cookies[url] = "${record.name}=${record.value}"
        }
    }

    private fun cookieHeaderForUrl(url: String): String? {
        val uri = runCatching { URI(url) }.getOrNull() ?: return null
        val host = uri.host?.lowercase() ?: return null
        val https = uri.scheme.equals("https", ignoreCase = true)
        val matches = loadRecords()
            .filter { record ->
                (host == record.domain || host.endsWith(".${record.domain}")) &&
                    (!record.secure || https)
            }
            .map { "${it.name}=${it.value}" }
        return matches.takeIf { it.isNotEmpty() }?.joinToString("; ")
    }

    private fun saveCookie(url: String, value: String) {
        val uri = runCatching { URI(url) }.getOrNull() ?: return
        val host = uri.host?.lowercase() ?: return
        val firstPart = value.substringBefore(";").trim()
        if (!firstPart.contains("=")) return
        val name = firstPart.substringBefore("=").trim()
        val cookieValue = firstPart.substringAfter("=").trim()
        if (name.isBlank()) return

        val current = loadRecords().filterNot {
            it.domain == host && it.path == "/" && it.name == name
        }
        val updated = current + SharedCookieRecord(
            domain = host,
            path = "/",
            name = name,
            value = cookieValue,
            secure = uri.scheme.equals("https", ignoreCase = true),
            updated_at = System.currentTimeMillis() / 1000.0,
        )
        saveRecords(updated)
    }

    private fun loadRecords(): List<SharedCookieRecord> {
        val path = sharedJarPath ?: return emptyList()
        if (!path.exists()) return emptyList()
        return runCatching {
            json.decodeFromString<SharedCookieJar>(Files.readString(path)).cookies
        }.getOrDefault(emptyList())
    }

    private fun saveRecords(records: List<SharedCookieRecord>) {
        val path = sharedJarPath ?: return
        runCatching {
            path.parent?.let { Files.createDirectories(it) }
            Files.writeString(path, json.encodeToString(SharedCookieJar(cookies = records)))
        }
    }

    companion object {
        @Volatile
        private var instance: CookieManager? = null

        @JvmStatic
        fun getInstance(): CookieManager {
            return instance ?: synchronized(this) {
                instance ?: CookieManager().also { instance = it }
            }
        }
    }
}

@Serializable
private data class SharedCookieJar(
    val version: Int = 1,
    val cookies: List<SharedCookieRecord> = emptyList(),
)

@Serializable
private data class SharedCookieRecord(
    val domain: String,
    val path: String = "/",
    val name: String,
    val value: String,
    val secure: Boolean = false,
    val updated_at: Double = 0.0,
)
