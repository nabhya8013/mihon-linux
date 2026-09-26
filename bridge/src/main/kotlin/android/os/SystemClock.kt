@file:Suppress("unused")
package android.os

/**
 * android.os.SystemClock stub.
 *
 * Rate-limiting interceptors bundled inside extensions call
 * `SystemClock.elapsedRealtime()` on every request, so this is reached by a
 * large share of sources.
 */
object SystemClock {
    private val bootNanos = System.nanoTime()

    @JvmStatic
    fun elapsedRealtime(): Long = (System.nanoTime() - bootNanos) / 1_000_000

    @JvmStatic
    fun elapsedRealtimeNanos(): Long = System.nanoTime() - bootNanos

    @JvmStatic
    fun uptimeMillis(): Long = elapsedRealtime()

    @JvmStatic
    fun currentThreadTimeMillis(): Long = System.currentTimeMillis()

    @JvmStatic
    fun sleep(ms: Long) {
        try {
            Thread.sleep(ms)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
        }
    }
}
