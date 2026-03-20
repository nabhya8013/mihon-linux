@file:Suppress("unused")
package android.content

import java.io.File

/**
 * Minimal Android Context stub for loading Tachiyomi extensions on desktop JVM.
 * Extensions use Context for SharedPreferences, file access, and package info.
 */
open class Context {

    private val prefsStore = mutableMapOf<String, SharedPreferences>()
    private val cacheDir = File(System.getProperty("java.io.tmpdir"), "mihon-bridge/cache")
    private val filesDir = File(
        System.getenv("XDG_DATA_HOME") ?: "${System.getProperty("user.home")}/.local/share",
        "mihon-linux/extensions"
    )

    open fun getSharedPreferences(name: String, mode: Int): SharedPreferences {
        return prefsStore.getOrPut(name) { SharedPreferencesImpl(name) }
    }

    open fun getCacheDir(): File {
        cacheDir.mkdirs()
        return cacheDir
    }

    open fun getFilesDir(): File {
        filesDir.mkdirs()
        return filesDir
    }

    open fun getPackageName(): String = "org.mihon.bridge"

    open fun getString(resId: Int): String = ""
    open fun getString(resId: Int, vararg formatArgs: Any): String = ""

    open fun getApplicationContext(): Context = this

    open fun getContentResolver(): Any? = null

    companion object {
        const val MODE_PRIVATE = 0
    }
}
