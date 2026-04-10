@file:Suppress("unused", "UNCHECKED_CAST")
package uy.kohesive.injekt.api

import java.lang.reflect.Type
import java.util.concurrent.ConcurrentHashMap

class InjektRegistrar {
    private val singletons = ConcurrentHashMap<Type, Any>()
    private val singletonsByName = ConcurrentHashMap<String, Any>()

    fun addSingleton(type: Type, instance: Any) {
        singletons[type] = instance
        singletonsByName[type.typeName] = instance
        if (type is Class<*>) {
            singletonsByName[type.name] = instance
            singletonsByName[type.canonicalName ?: type.name] = instance
        }
    }

    fun get(type: Type): Any? {
        return singletons[type]
            ?: singletonsByName[type.typeName]
            ?: (type as? Class<*>)?.let { cls ->
                singletonsByName[cls.name]
                    ?: singletonsByName[cls.canonicalName ?: cls.name]
            }
    }
}

open class InjektScope(
    val registrar: InjektRegistrar = InjektRegistrar()
) : InjektFactory {

    override fun getInstance(type: Type): Any {
        return registrar.get(type)
            ?: throw IllegalStateException(
                "No Injekt binding for ${type.typeName}. Register the dependency before loading the extension."
            )
    }

    override fun getInstanceOrNull(type: Type): Any? = registrar.get(type)

    fun addSingleton(type: Type, instance: Any) {
        registrar.addSingleton(type, instance)
    }

    inline fun <reified T : Any> addSingleton(instance: T) {
        addSingleton(fullType<T>().type, instance)
    }

    inline fun <reified T : Any> get(): T = getInstance(fullType<T>().type) as T

    inline fun <reified T : Any> getOrNull(): T? = getInstanceOrNull(fullType<T>().type) as? T

    fun importModule(module: InjektModule): InjektScope {
        module.registerInjectables(this)
        return this
    }
}
