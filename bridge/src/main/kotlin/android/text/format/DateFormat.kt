@file:Suppress("unused")
package android.text.format

import java.text.SimpleDateFormat
import java.util.Locale

/**
 * android.text.format.DateFormat stub. Extensions use it to build locale-aware
 * parsers for chapter upload dates.
 */
object DateFormat {
    @JvmStatic
    fun getDateFormat(context: Any?): java.text.DateFormat =
        java.text.DateFormat.getDateInstance(java.text.DateFormat.SHORT, Locale.getDefault())

    @JvmStatic
    fun getTimeFormat(context: Any?): java.text.DateFormat =
        java.text.DateFormat.getTimeInstance(java.text.DateFormat.SHORT, Locale.getDefault())

    @JvmStatic
    fun getLongDateFormat(context: Any?): java.text.DateFormat =
        java.text.DateFormat.getDateInstance(java.text.DateFormat.LONG, Locale.getDefault())

    @JvmStatic
    fun getMediumDateFormat(context: Any?): java.text.DateFormat =
        java.text.DateFormat.getDateInstance(java.text.DateFormat.MEDIUM, Locale.getDefault())

    @JvmStatic
    fun is24HourFormat(context: Any?): Boolean = true

    @JvmStatic
    fun format(inFormat: CharSequence, inDate: java.util.Date): CharSequence =
        SimpleDateFormat(inFormat.toString(), Locale.getDefault()).format(inDate)

    @JvmStatic
    fun format(inFormat: CharSequence, inTimeInMillis: Long): CharSequence =
        format(inFormat, java.util.Date(inTimeInMillis))
}
