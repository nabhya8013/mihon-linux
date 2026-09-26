@file:Suppress("unused", "UNUSED_PARAMETER")
package android.widget

import android.text.InputFilter
import android.text.TextWatcher

/**
 * android.widget.EditText / TextView stubs.
 *
 * Only reachable through EditTextPreference.OnBindEditTextListener, which never
 * fires on desktop. They exist so extension classes that reference these types
 * can be linked.
 */
open class TextView {
    var text: CharSequence? = null
    var hint: CharSequence? = null
    var inputType: Int = 0
    var error: CharSequence? = null
    var filters: Array<InputFilter> = emptyArray()

    open fun addTextChangedListener(watcher: TextWatcher?) {}
    open fun removeTextChangedListener(watcher: TextWatcher?) {}
    open fun setSelection(index: Int) {}
    open fun setSingleLine() {}
}

open class EditText : TextView()

open class Toast {
    companion object {
        const val LENGTH_SHORT = 0
        const val LENGTH_LONG = 1

        @JvmStatic
        fun makeText(context: Any?, text: CharSequence?, duration: Int): Toast {
            System.err.println("[toast] $text")
            return Toast()
        }
    }

    fun show() {}
}
