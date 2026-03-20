package org.mihon.bridge

import android.app.Application
import eu.kanade.tachiyomi.source.CatalogueSource
import eu.kanade.tachiyomi.source.Source
import eu.kanade.tachiyomi.source.SourceFactory
import eu.kanade.tachiyomi.source.online.HttpSource
import java.io.File
import java.net.URLClassLoader

/**
 * Loads Tachiyomi extension JARs (converted from APK/DEX) into the JVM,
 * instantiates extension classes, and caches loaded instances.
 */
object ExtensionLoader {

    /** Shared mock Application context for extensions that need it */
    private val mockContext = Application()

    /** ClassLoader per JAR path */
    private val classLoaders = mutableMapOf<String, URLClassLoader>()

    /** Loaded extension instances: extensionId (Long) -> Source */
    private val loadedSources = mutableMapOf<Long, Source>()

    /** Loaded extension metadata: className -> Source */
    private val loadedByClass = mutableMapOf<String, List<Source>>()

    /**
     * Load one or more extension classes from a JAR file.
     *
     * @param jarPath  Absolute path to the JAR file (dex2jar output)
     * @param classNames  Semicolon-separated list of fully-qualified class names
     *                    (from AndroidManifest's tachiyomi.extension.class)
     * @return List of loaded Sources
     */
    fun loadExtension(jarPath: String, classNames: String): List<Source> {
        val file = File(jarPath)
        if (!file.exists()) {
            throw IllegalArgumentException("Extension JAR not found: $jarPath")
        }

        val parentCl = this::class.java.classLoader
        val classLoader = classLoaders.getOrPut(jarPath) {
            URLClassLoader(arrayOf(file.toURI().toURL()), parentCl)
        }

        val names = classNames.split(";").map { it.trim() }.filter { it.isNotEmpty() }
        val results = mutableListOf<Source>()

        for (className in names) {
            // Already loaded?
            val existing = loadedByClass[className]
            if (existing != null) {
                results.addAll(existing)
                continue
            }

            try {
                val clazz = classLoader.loadClass(className)
                val newSources = instantiateSources(clazz)
                loadedByClass[className] = newSources
                for (instance in newSources) {
                    loadedSources[instance.id] = instance
                    results.add(instance)
                    System.err.println("[ExtensionLoader] Loaded: ${instance.name} (${instance.id}) from $className")
                }
            } catch (e: Throwable) {
                System.err.println("[ExtensionLoader] Failed to load $className: ${e.message}")
                e.printStackTrace(System.err)
                throw Exception("Failed to load extension class $className: ${e.message}", e)
            }
        }

        return results
    }

    /**
     * Try to instantiate a Source class using various constructor signatures.
     */
    private fun instantiateSources(clazz: Class<*>): List<Source> {
        var instance: Any? = null
        
        // Try 1: No-arg constructor
        try {
            instance = clazz.getDeclaredConstructor().newInstance()
        } catch (_: NoSuchMethodException) {}

        // Try 2: Constructor(Application) — some extensions need context
        if (instance == null) {
            try {
                val ctor = clazz.getDeclaredConstructor(android.app.Application::class.java)
                instance = ctor.newInstance(mockContext)
            } catch (_: NoSuchMethodException) {}
        }

        // Try 3: Constructor(Context)
        if (instance == null) {
            try {
                val ctor = clazz.getDeclaredConstructor(android.content.Context::class.java)
                instance = ctor.newInstance(mockContext)
            } catch (_: NoSuchMethodException) {}
        }

        // Try 4: Constructor(Long) — multi-source extensions with source ID
        if (instance == null) {
            try {
                val ctor = clazz.getDeclaredConstructor(Long::class.java)
                instance = ctor.newInstance(0L)
            } catch (_: NoSuchMethodException) {}
        }

        // Try 5: Constructor(String) — some multi-source with language arg
        if (instance == null) {
            try {
                val ctor = clazz.getDeclaredConstructor(String::class.java)
                instance = ctor.newInstance("en")
            } catch (_: NoSuchMethodException) {}
        }

        if (instance == null) {
            throw UnsupportedOperationException(
                "Could not instantiate ${clazz.name}: no matching constructor found. " +
                "Available constructors: ${clazz.declaredConstructors.map { it.parameterTypes.toList() }}"
            )
        }

        return when (instance) {
            is SourceFactory -> instance.createSources()
            is Source -> listOf(instance)
            else -> throw UnsupportedOperationException("${clazz.name} is neither Source nor SourceFactory")
        }
    }

    /** Get a loaded source by its ID */
    fun getSource(id: Long): Source? = loadedSources[id]

    /** Get a loaded source as CatalogueSource (for browsing) */
    fun getCatalogueSource(id: Long): CatalogueSource? = loadedSources[id] as? CatalogueSource

    /** Get a loaded source as HttpSource */
    fun getHttpSource(id: Long): HttpSource? = loadedSources[id] as? HttpSource

    /** List all loaded sources */
    fun getAllSources(): List<Source> = loadedSources.values.toList()

    /** Unload all extensions (cleanup) */
    fun unloadAll() {
        loadedSources.clear()
        loadedByClass.clear()
        classLoaders.values.forEach { it.close() }
        classLoaders.clear()
    }
}
