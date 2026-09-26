package app.cash.quickjs

import java.io.Closeable
import org.mozilla.javascript.Context
import org.mozilla.javascript.ContextFactory
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined

/**
 * `app.cash.quickjs.QuickJs` implemented on Rhino.
 *
 * Many extensions deobfuscate page URLs by evaluating a snippet of the site's
 * own JavaScript. Android ships QuickJS as a native library; on desktop we run
 * the same scripts through Rhino, which needs no native code.
 *
 * Rhino is interpreted-only here (`optimizationLevel = -1`) so it works on a JRE
 * without bytecode generation, and script execution is capped so a hostile or
 * runaway script cannot hang the bridge.
 */
class QuickJs private constructor() : Closeable {

    private val contextFactory = SafeContextFactory()
    private var scope: ScriptableObject? = null
    private var closed = false

    companion object {
        @JvmStatic
        fun create(): QuickJs = QuickJs()

        /** Wall-clock cap for a single evaluate() call. */
        private const val SCRIPT_TIMEOUT_MS = 10_000L
    }

    private class SafeContextFactory : ContextFactory() {
        override fun makeContext(): Context {
            val cx = super.makeContext()
            cx.optimizationLevel = -1
            cx.languageVersion = Context.VERSION_ES6
            cx.instructionObserverThreshold = 10_000
            return cx
        }

        override fun observeInstructionCount(cx: Context, instructionCount: Int) {
            val start = cx.getThreadLocal(START_KEY) as? Long ?: return
            if (System.currentTimeMillis() - start > SCRIPT_TIMEOUT_MS) {
                throw IllegalStateException("QuickJs: script exceeded ${SCRIPT_TIMEOUT_MS}ms")
            }
        }

        companion object {
            const val START_KEY = "quickjs.start"
        }
    }

    private fun <T> withContext(block: (Context, ScriptableObject) -> T): T {
        check(!closed) { "QuickJs instance is closed" }
        val cx = contextFactory.enterContext()
        try {
            cx.putThreadLocal(SafeContextFactory.START_KEY, System.currentTimeMillis())
            val active = scope ?: cx.initSafeStandardObjects().also { scope = it }
            return block(cx, active)
        } finally {
            Context.exit()
        }
    }

    fun evaluate(script: String, fileName: String = "?"): Any? = withContext { cx, sc ->
        val result = cx.evaluateString(sc, script, fileName, 1, null)
        unwrap(result)
    }

    /** Expose a Java/Kotlin object to scripts as a global. */
    fun set(name: String, type: Class<*>, instance: Any) = withContext { cx, sc ->
        ScriptableObject.putProperty(sc, name, Context.javaToJS(instance, sc))
    }

    /** Read a global out of the script scope, coerced to [type]. */
    @Suppress("UNCHECKED_CAST")
    fun <T> get(name: String, type: Class<T>): T = withContext { _, sc ->
        val value = ScriptableObject.getProperty(sc, name)
        if (value == Scriptable.NOT_FOUND) {
            throw NoSuchElementException("QuickJs: no global named '$name'")
        }
        Context.jsToJava(value, type) as T
    }

    override fun close() {
        closed = true
        scope = null
    }

    private fun unwrap(value: Any?): Any? = when (value) {
        null, is Undefined -> null
        is org.mozilla.javascript.NativeJavaObject -> value.unwrap()
        is CharSequence -> value.toString()
        is Number, is Boolean -> value
        is Scriptable -> Context.jsToJava(value, Any::class.java)
        else -> value
    }
}
