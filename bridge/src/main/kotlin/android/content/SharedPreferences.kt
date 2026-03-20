@file:Suppress("unused")
package android.content

import java.io.File
import java.util.Properties

/**
 * Map-backed SharedPreferences implementation for desktop JVM.
 * Persists to a .properties file in XDG_DATA_HOME.
 */
interface SharedPreferences {
    fun getBoolean(key: String, defValue: Boolean): Boolean
    fun getInt(key: String, defValue: Int): Int
    fun getLong(key: String, defValue: Long): Long
    fun getFloat(key: String, defValue: Float): Float
    fun getString(key: String, defValue: String?): String?
    fun getStringSet(key: String, defValues: Set<String>?): Set<String>?
    fun getAll(): Map<String, *>
    fun contains(key: String): Boolean
    fun edit(): Editor

    interface Editor {
        fun putBoolean(key: String, value: Boolean): Editor
        fun putInt(key: String, value: Int): Editor
        fun putLong(key: String, value: Long): Editor
        fun putFloat(key: String, value: Float): Editor
        fun putString(key: String, value: String?): Editor
        fun putStringSet(key: String, values: Set<String>?): Editor
        fun remove(key: String): Editor
        fun clear(): Editor
        fun commit(): Boolean
        fun apply()
    }

    fun registerOnSharedPreferenceChangeListener(listener: OnSharedPreferenceChangeListener)
    fun unregisterOnSharedPreferenceChangeListener(listener: OnSharedPreferenceChangeListener)

    interface OnSharedPreferenceChangeListener {
        fun onSharedPreferenceChanged(prefs: SharedPreferences, key: String)
    }
}

class SharedPreferencesImpl(private val name: String) : SharedPreferences {

    private val data = mutableMapOf<String, Any?>()
    private val listeners = mutableListOf<SharedPreferences.OnSharedPreferenceChangeListener>()

    private val persistFile: File by lazy {
        val dir = File(
            System.getenv("XDG_DATA_HOME") ?: "${System.getProperty("user.home")}/.local/share",
            "mihon-linux/prefs"
        )
        dir.mkdirs()
        File(dir, "$name.properties")
    }

    init {
        loadFromDisk()
    }

    private fun loadFromDisk() {
        if (persistFile.exists()) {
            val props = Properties()
            persistFile.inputStream().use { props.load(it) }
            props.forEach { (k, v) -> data[k.toString()] = v.toString() }
        }
    }

    private fun saveToDisk() {
        val props = Properties()
        data.forEach { (k, v) -> if (v != null) props[k] = v.toString() }
        persistFile.outputStream().use { props.store(it, "mihon-bridge prefs: $name") }
    }

    override fun getBoolean(key: String, defValue: Boolean) =
        data[key]?.toString()?.toBooleanStrictOrNull() ?: defValue

    override fun getInt(key: String, defValue: Int) =
        data[key]?.toString()?.toIntOrNull() ?: defValue

    override fun getLong(key: String, defValue: Long) =
        data[key]?.toString()?.toLongOrNull() ?: defValue

    override fun getFloat(key: String, defValue: Float) =
        data[key]?.toString()?.toFloatOrNull() ?: defValue

    override fun getString(key: String, defValue: String?): String? =
        data[key]?.toString() ?: defValue

    override fun getStringSet(key: String, defValues: Set<String>?): Set<String>? {
        val raw = data[key]?.toString() ?: return defValues
        return raw.split("\u001f").toSet()
    }

    override fun getAll(): Map<String, *> = data.toMap()
    override fun contains(key: String) = key in data

    override fun edit(): SharedPreferences.Editor = EditorImpl()

    override fun registerOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) {
        listeners.add(listener)
    }

    override fun unregisterOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener) {
        listeners.remove(listener)
    }

    private inner class EditorImpl : SharedPreferences.Editor {
        private val pending = mutableMapOf<String, Any?>()
        private val removals = mutableSetOf<String>()
        private var clearAll = false

        override fun putBoolean(key: String, value: Boolean) = apply { pending[key] = value }
        override fun putInt(key: String, value: Int) = apply { pending[key] = value }
        override fun putLong(key: String, value: Long) = apply { pending[key] = value }
        override fun putFloat(key: String, value: Float) = apply { pending[key] = value }
        override fun putString(key: String, value: String?) = apply { pending[key] = value }
        override fun putStringSet(key: String, values: Set<String>?) = apply {
            pending[key] = values?.joinToString("\u001f")
        }
        override fun remove(key: String) = apply { removals.add(key) }
        override fun clear() = apply { clearAll = true }

        override fun commit(): Boolean {
            applyChanges()
            saveToDisk()
            return true
        }

        override fun apply() {
            applyChanges()
            // Save async
            Thread { saveToDisk() }.start()
        }

        private fun applyChanges() {
            if (clearAll) data.clear()
            removals.forEach { data.remove(it) }
            pending.forEach { (k, v) -> data[k] = v }
            val changedKeys = pending.keys + removals
            changedKeys.forEach { key ->
                listeners.forEach { it.onSharedPreferenceChanged(this@SharedPreferencesImpl, key) }
            }
        }
    }
}
