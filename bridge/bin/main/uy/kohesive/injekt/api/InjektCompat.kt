@file:Suppress("unused", "UNCHECKED_CAST")
package uy.kohesive.injekt.api

import java.lang.reflect.ParameterizedType
import java.lang.reflect.Type

interface TypeReference {
    val type: Type
}

open class FullTypeReference<T> : TypeReference {
    override val type: Type by lazy {
        val superType = javaClass.genericSuperclass
        if (superType is ParameterizedType) {
            superType.actualTypeArguments.firstOrNull() ?: Any::class.java
        } else {
            Any::class.java
        }
    }
}

interface InjektFactory {
    fun getInstance(type: Type): Any
    fun getInstanceOrNull(type: Type): Any?
}

interface InjektModule {
    fun registerInjectables(factory: InjektScope)
}

interface InjektMain {
    val injekt: InjektScope
}

fun InjektFactory.get(type: Type): Any = getInstance(type)
fun InjektFactory.getOrNull(type: Type): Any? = getInstanceOrNull(type)

inline fun <reified T : Any> fullType(): TypeReference = object : FullTypeReference<T>() {}

inline fun <reified T : Any> InjektFactory.get(): T = getInstance(fullType<T>().type) as T
inline fun <reified T : Any> InjektFactory.getOrNull(): T? = getInstanceOrNull(fullType<T>().type) as? T
