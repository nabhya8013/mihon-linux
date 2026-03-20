@file:JvmName("InjektKt")
@file:Suppress("unused", "UNCHECKED_CAST")
package uy.kohesive.injekt

import uy.kohesive.injekt.api.InjektMain
import uy.kohesive.injekt.api.InjektScope
import uy.kohesive.injekt.api.InjektModule
import uy.kohesive.injekt.api.fullType

/**
 * Minimal Injekt stub for desktop JVM.
 *
 * Tachiyomi extensions use `Injekt.get<T>()` to resolve dependencies like
 * NetworkHelper and Application. This top-level val compiles to a
 * static getInjekt() getter on InjektKt, matching the real library's ABI.
 */
val Injekt: InjektScope = InjektScope()

/**
 * Additional entrypoint shape some extensions expect.
 */
object InjektMainImpl : InjektMain {
    override val injekt: InjektScope
        get() = Injekt
}

fun importModule(module: InjektModule): InjektScope = Injekt.importModule(module)

/**
 * The `injectLazy()` delegate used by extensions:
 *   private val network: NetworkHelper by injectLazy()
 */
inline fun <reified T : Any> injectLazy(): Lazy<T> = lazy {
    Injekt.getInstance(fullType<T>().type) as T
}
