@file:Suppress("unused")
package eu.kanade.tachiyomi

/**
 * `eu.kanade.tachiyomi.AppInfo` / `BuildConfig` stubs.
 *
 * Extensions read these to gate behaviour on the host app version — for example
 * MangaDex checks the version code before using a newer API path. Reporting a
 * recent Mihon build keeps them on their modern code paths.
 */
object AppInfo {
    // Deliberately NOT @JvmStatic: upstream AppInfo is a Kotlin `object`, so
    // extensions compile calls as AppInfo.INSTANCE.getVersionName(). Marking
    // these static makes those call sites fail with IncompatibleClassChangeError.
    fun getVersionCode(): Int = VERSION_CODE

    fun getVersionName(): String = VERSION_NAME

    const val VERSION_CODE = 122
    const val VERSION_NAME = "0.20.1"
}

object BuildConfig {
    const val APPLICATION_ID = "app.mihon"
    const val VERSION_CODE = AppInfo.VERSION_CODE
    const val VERSION_NAME = AppInfo.VERSION_NAME
    const val DEBUG = false
    const val BUILD_TYPE = "release"
    const val FLAVOR = "standard"
}
