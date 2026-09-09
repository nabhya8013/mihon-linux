@file:Suppress("unused", "UNUSED_PARAMETER")
package android.os

import java.util.concurrent.Executors

/**
 * android.os.Handler / Looper stubs.
 *
 * A few extensions post work to the main looper (usually to show a toast).
 * On desktop there is no UI thread to hop onto, so posted work runs on a
 * single background executor and delays are honoured.
 */
class Looper private constructor() {
    companion object {
        private val main = Looper()

        @JvmStatic
        fun getMainLooper(): Looper = main

        @JvmStatic
        fun myLooper(): Looper = main

        @JvmStatic
        fun prepare() {}

        @JvmStatic
        fun loop() {}
    }
}

open class Handler(looper: Looper? = null) {

    private val executor = shared

    open fun post(r: Runnable): Boolean {
        executor.execute(r)
        return true
    }

    open fun postDelayed(r: Runnable, delayMillis: Long): Boolean {
        executor.execute {
            if (delayMillis > 0) SystemClock.sleep(delayMillis)
            r.run()
        }
        return true
    }

    open fun removeCallbacksAndMessages(token: Any?) {}

    companion object {
        private val shared = Executors.newSingleThreadExecutor { r ->
            Thread(r, "mihon-handler").apply { isDaemon = true }
        }
    }
}
