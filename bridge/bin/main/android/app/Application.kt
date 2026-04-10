@file:Suppress("unused")
package android.app

import android.content.Context

/**
 * Minimal Application stub. Some extensions require Application context.
 */
open class Application : Context() {
    open fun onCreate() {}
}
