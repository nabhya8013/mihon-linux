@file:Suppress("unused")
package android.webkit

/**
 * Stub CookieManager for desktop JVM.
 * Some extensions use CookieManager to persist/read cookies from WebView.
 * On desktop we back this with an in-memory cookie store.
 */
class CookieManager private constructor() {

    private val cookies = mutableMapOf<String, String>()

    fun getCookie(url: String): String? = cookies[url]

    fun setCookie(url: String, value: String) {
        cookies[url] = value
    }

    fun removeAllCookies(callback: ((Boolean) -> Unit)?) {
        cookies.clear()
        callback?.invoke(true)
    }

    fun flush() {
        // No-op on desktop
    }

    fun setAcceptCookie(accept: Boolean) {
        // No-op
    }

    fun hasCookies(): Boolean = cookies.isNotEmpty()

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
