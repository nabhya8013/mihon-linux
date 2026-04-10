package app.cash.quickjs

import java.io.Closeable

/**
 * Stub for app.cash.quickjs.QuickJs to allow Tachiyomi extensions
 * that depend on it to be class-loaded in our JVM bridge.
 * 
 * Note: Actual Javascript execution is not supported by this stub.
 * Extensions relying heavily on JS evaluation will fall back to errors
 * during runtime if they actually call evaluate().
 */
class QuickJs private constructor(private val ptr: Long) : Closeable {

    companion object {
        @JvmStatic
        fun create(): QuickJs {
            return QuickJs(0L)
        }
    }

    fun evaluate(script: String, fileName: String = "?"): Any? {
        System.err.println("[QuickJs Stub] evaluate called: $fileName")
        return null
    }

    fun set(name: String, type: Class<*>, instance: Any) {
        System.err.println("[QuickJs Stub] set called: $name")
    }

    fun <T> get(name: String, type: Class<T>): T {
        System.err.println("[QuickJs Stub] get called: $name")
        throw UnsupportedOperationException("QuickJs JS execution is stubbed on JVM.")
    }

    override fun close() {
        // No-op
    }
}
