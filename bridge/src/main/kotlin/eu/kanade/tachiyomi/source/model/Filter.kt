package eu.kanade.tachiyomi.source.model

/**
 * Tachiyomi Filter and FilterList stubs.
 * Extensions define custom filters (genre checkboxes, sort options, etc.)
 */
sealed class Filter<T>(val name: String, var state: T) {

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (javaClass != other?.javaClass) return false
        other as Filter<*>
        return name == other.name && state == other.state
    }

    override fun hashCode(): Int = 31 * name.hashCode() + (state?.hashCode() ?: 0)

    open class Header(name: String) : Filter<Unit>(name, Unit)
    open class Separator(name: String = "") : Filter<Unit>(name, Unit)
    abstract class Select<V>(name: String, val values: Array<V>, state: Int = 0) : Filter<Int>(name, state) {
        override fun toString(): String = values[state].toString()
    }
    abstract class Text(name: String, state: String = "") : Filter<String>(name, state)
    abstract class CheckBox(name: String, state: Boolean = false) : Filter<Boolean>(name, state)
    abstract class TriState(name: String, state: Int = STATE_IGNORE) : Filter<Int>(name, state) {
        // Extensions branch on these constantly when building query parameters;
        // without them a source fails at runtime with NoSuchMethodError.
        fun isIgnored(): Boolean = state == STATE_IGNORE
        fun isIncluded(): Boolean = state == STATE_INCLUDE
        fun isExcluded(): Boolean = state == STATE_EXCLUDE

        companion object {
            const val STATE_IGNORE = 0
            const val STATE_INCLUDE = 1
            const val STATE_EXCLUDE = 2
        }
    }
    abstract class Group<V>(name: String, state: List<V>) : Filter<List<V>>(name, state)
    abstract class Sort(name: String, val values: Array<String>, state: Selection? = null) :
        Filter<Sort.Selection?>(name, state) {
        data class Selection(val index: Int, val ascending: Boolean)
    }
}

class FilterList(vararg filters: Filter<*>) : List<Filter<*>> by filters.toList() {
    constructor(filters: List<Filter<*>>) : this(*filters.toTypedArray())
}

/**
 * How the source wants its manga listing refreshed.
 */
enum class UpdateStrategy {
    ALWAYS_UPDATE,
    ONLY_FETCH_ONCE,
}
