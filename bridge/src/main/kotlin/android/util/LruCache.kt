@file:Suppress("unused")
package android.util

/**
 * android.util.LruCache stub backed by a LinkedHashMap in access order.
 * Thread-safe like the Android original.
 */
open class LruCache<K : Any, V : Any>(private val maxSize: Int) {

    private val map = object : LinkedHashMap<K, V>(0, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<K, V>): Boolean {
            val over = size > this@LruCache.maxSize
            if (over) entryRemoved(true, eldest.key, eldest.value, null)
            return over
        }
    }

    @Synchronized
    open fun get(key: K): V? = map[key] ?: create(key)?.also { map[key] = it }

    @Synchronized
    open fun put(key: K, value: V): V? = map.put(key, value)

    @Synchronized
    open fun remove(key: K): V? = map.remove(key)?.also { entryRemoved(false, key, it, null) }

    @Synchronized
    open fun evictAll() {
        val entries = map.entries.toList()
        map.clear()
        entries.forEach { entryRemoved(true, it.key, it.value, null) }
    }

    @Synchronized
    open fun size(): Int = map.size

    open fun maxSize(): Int = maxSize

    @Synchronized
    open fun snapshot(): Map<K, V> = LinkedHashMap(map)

    protected open fun create(key: K): V? = null

    protected open fun entryRemoved(evicted: Boolean, key: K, oldValue: V, newValue: V?) {}

    protected open fun sizeOf(key: K, value: V): Int = 1
}
