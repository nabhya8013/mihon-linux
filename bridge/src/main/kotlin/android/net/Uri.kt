@file:Suppress("unused")
package android.net

import java.net.URI
import java.net.URLEncoder

/**
 * Android Uri stub backed by java.net.URI.
 */
class Uri private constructor(private val uriString: String) {

    override fun toString(): String = uriString

    fun getScheme(): String? = try { URI(uriString).scheme } catch (_: Exception) { null }
    fun getHost(): String? = try { URI(uriString).host } catch (_: Exception) { null }
    fun getPort(): Int = try { URI(uriString).port } catch (_: Exception) { -1 }
    fun getPath(): String? = try { URI(uriString).path } catch (_: Exception) { null }
    fun getQuery(): String? = try { URI(uriString).query } catch (_: Exception) { null }
    fun getFragment(): String? = try { URI(uriString).fragment } catch (_: Exception) { null }
    fun getLastPathSegment(): String? = getPath()?.trimEnd('/')?.substringAfterLast('/')

    fun getQueryParameter(key: String): String? {
        val query = getQuery() ?: return null
        return query.split("&")
            .map { it.split("=", limit = 2) }
            .firstOrNull { it[0] == key }
            ?.getOrNull(1)
    }

    fun buildUpon(): Builder = Builder(uriString)

    class Builder(baseUri: String = "") {
        private var scheme: String? = null
        private var authority: String? = null
        private var pathSegments = mutableListOf<String>()
        private var queryParams = mutableListOf<Pair<String, String>>()
        private var fragment: String? = null
        private var base: String = baseUri

        fun scheme(scheme: String) = apply { this.scheme = scheme }
        fun authority(authority: String) = apply { this.authority = authority }
        fun appendPath(path: String) = apply { pathSegments.add(path) }
        fun appendQueryParameter(key: String, value: String) = apply {
            queryParams.add(key to value)
        }
        fun encodedPath(path: String) = apply { pathSegments.clear(); pathSegments.add(path.trimStart('/')) }
        fun fragment(fragment: String) = apply { this.fragment = fragment }
        fun clearQuery() = apply { queryParams.clear() }

        fun build(): Uri {
            if (base.isNotEmpty() && scheme == null && authority == null && pathSegments.isEmpty() && queryParams.isEmpty()) {
                return parse(base)
            }
            val sb = StringBuilder()
            if (scheme != null) sb.append("$scheme://")
            if (authority != null) sb.append(authority)
            if (pathSegments.isNotEmpty()) {
                sb.append("/")
                sb.append(pathSegments.joinToString("/"))
            }
            if (queryParams.isNotEmpty()) {
                sb.append("?")
                sb.append(queryParams.joinToString("&") {
                    "${URLEncoder.encode(it.first, "UTF-8")}=${URLEncoder.encode(it.second, "UTF-8")}"
                })
            }
            if (fragment != null) sb.append("#$fragment")
            return Uri(sb.toString())
        }
    }

    companion object {
        @JvmStatic
        fun parse(uriString: String): Uri = Uri(uriString)

        @JvmStatic
        fun encode(s: String): String = URLEncoder.encode(s, "UTF-8")
    }
}
