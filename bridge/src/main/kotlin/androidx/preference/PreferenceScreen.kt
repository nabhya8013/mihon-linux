package androidx.preference

import android.content.Context
import android.content.SharedPreferences

/**
 * Minimal androidx.preference model.
 *
 * Extensions build their settings UI by calling `screen.addPreference(...)` inside
 * `ConfigurableSource.setupPreferenceScreen`. The bridge walks the resulting tree,
 * serialises it to JSON for the GTK UI, and writes changes back through the same
 * SharedPreferences the extension reads at runtime.
 */
open class Preference(var context: Context? = null) {
    var key: String = ""
    var title: CharSequence? = null
    var summary: CharSequence? = null
    var isEnabled: Boolean = true
    var isVisible: Boolean = true
    var isPersistent: Boolean = true

    /**
     * Backing storage for the default value and change listener.
     *
     * These are deliberately NOT Kotlin `var`s named `defaultValue` /
     * `onPreferenceChangeListener`: the generated setters would collide with the
     * explicit `setDefaultValue` / `setOnPreferenceChangeListener` methods that
     * compiled extensions actually call.
     */
    @JvmField
    var storedDefault: Any? = null

    @JvmField
    var changeListener: OnPreferenceChangeListener? = null

    /** The type tag sent to the client UI. */
    open val widgetType: String get() = "preference"

    fun setDefaultValue(value: Any?) {
        storedDefault = value
    }

    fun getDefaultValue(): Any? = storedDefault

    fun setOnPreferenceChangeListener(listener: OnPreferenceChangeListener?) {
        changeListener = listener
    }

    fun getOnPreferenceChangeListener(): OnPreferenceChangeListener? = changeListener

    /** Invoke the extension's listener, mirroring androidx behaviour. */
    fun callChangeListener(newValue: Any): Boolean =
        changeListener?.onPreferenceChange(this, newValue) ?: true

    fun interface OnPreferenceChangeListener {
        fun onPreferenceChange(preference: Preference, newValue: Any): Boolean
    }
}

open class PreferenceGroup(context: Context? = null) : Preference(context) {
    private val children = mutableListOf<Preference>()

    open fun addPreference(preference: Preference): Boolean {
        children.add(preference)
        return true
    }

    fun removePreference(preference: Preference): Boolean = children.remove(preference)

    val preferenceCount: Int get() = children.size

    fun getPreference(index: Int): Preference = children[index]

    fun getPreferences(): List<Preference> = children.toList()

    fun findPreference(key: CharSequence): Preference? =
        children.firstOrNull { it.key == key }
            ?: children.filterIsInstance<PreferenceGroup>()
                .firstNotNullOfOrNull { it.findPreference(key) }
}

open class PreferenceCategory(context: Context? = null) : PreferenceGroup(context) {
    override val widgetType: String get() = "category"
}

open class PreferenceScreen(context: Context? = null) : PreferenceGroup(context) {
    override val widgetType: String get() = "screen"
}

open class EditTextPreference(context: Context? = null) : Preference(context) {
    override val widgetType: String get() = "text"
    var dialogTitle: CharSequence? = null
    var dialogMessage: CharSequence? = null
    var text: String? = null

    /**
     * Extensions call `setOnBindEditTextListener` to configure the input type
     * or attach a validator. There is no dialog on desktop, so the listener is
     * stored and never invoked — but the nested interface must exist or the
     * whole setupPreferenceScreen call fails to link.
     */
    @JvmField
    var bindEditTextListener: OnBindEditTextListener? = null

    fun setOnBindEditTextListener(listener: OnBindEditTextListener?) {
        bindEditTextListener = listener
    }

    fun interface OnBindEditTextListener {
        fun onBindEditText(editText: android.widget.EditText)
    }
}

open class ListPreference(context: Context? = null) : Preference(context) {
    override val widgetType: String get() = "list"
    var entries: Array<CharSequence> = emptyArray()
    var entryValues: Array<CharSequence> = emptyArray()
    var value: String? = null
    var dialogTitle: CharSequence? = null

    fun findIndexOfValue(value: String?): Int = entryValues.indexOfFirst { it.toString() == value }
}

open class MultiSelectListPreference(context: Context? = null) : Preference(context) {
    override val widgetType: String get() = "multi_list"
    var entries: Array<CharSequence> = emptyArray()
    var entryValues: Array<CharSequence> = emptyArray()
    var values: Set<String> = emptySet()
    var dialogTitle: CharSequence? = null
}

open class TwoStatePreference(context: Context? = null) : Preference(context) {
    override val widgetType: String get() = "switch"
    var isChecked: Boolean = false
    var summaryOn: CharSequence? = null
    var summaryOff: CharSequence? = null
}

open class SwitchPreferenceCompat(context: Context? = null) : TwoStatePreference(context)

open class CheckBoxPreference(context: Context? = null) : TwoStatePreference(context) {
    override val widgetType: String get() = "checkbox"
}

object PreferenceManager {
    @JvmStatic
    fun getDefaultSharedPreferences(context: Context): SharedPreferences =
        context.getSharedPreferences("${context.getPackageName()}_preferences", Context.MODE_PRIVATE)
}
