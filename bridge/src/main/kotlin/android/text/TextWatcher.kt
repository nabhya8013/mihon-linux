@file:Suppress("unused")
package android.text

/**
 * android.text.TextWatcher / Editable stubs.
 *
 * Extensions with an EditTextPreference attach a TextWatcher to validate input.
 * The interface only needs to exist for those classes to resolve — nothing on
 * desktop ever fires the callbacks.
 */
interface TextWatcher {
    fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
    fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
    fun afterTextChanged(s: Editable?) {}
}

interface Editable : CharSequence {
    fun clear() {}
    fun append(text: CharSequence?): Editable = this
}

interface InputFilter {
    fun filter(
        source: CharSequence?, start: Int, end: Int,
        dest: Spanned?, dstart: Int, dend: Int,
    ): CharSequence?
}

interface Spanned : CharSequence

interface Spannable : Spanned
