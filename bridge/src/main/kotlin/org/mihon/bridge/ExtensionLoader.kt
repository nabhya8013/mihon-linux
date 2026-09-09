package org.mihon.bridge

import android.app.Application
import eu.kanade.tachiyomi.source.CatalogueSource
import eu.kanade.tachiyomi.source.Source
import eu.kanade.tachiyomi.source.SourceFactory
import eu.kanade.tachiyomi.source.online.HttpSource
import java.io.File
import java.net.URLClassLoader
import java.util.jar.JarFile

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

    /**
     * Loaded sources keyed by "jarPath|className".
     *
     * The jar path is part of the key because Keiyoushi names the generated
     * factory in EVERY extension `keiyoushi.source.Generated` — keying on the
     * class name alone made the second extension installed collide with the
     * first and return its sources.
     */
    private val loadedByClass = mutableMapOf<String, List<Source>>()

    /** Source id -> NSFW flag, taken from the APK manifest. */
    private val nsfwFlags = mutableMapOf<Long, Boolean>()

    /** Source id -> originating JAR path, so one extension can be unloaded alone. */
    private val sourceJar = mutableMapOf<Long, String>()

    fun isNsfw(id: Long): Boolean = nsfwFlags[id] ?: false

    /**
     * Load one or more extension classes from a JAR file.
     *
     * @param jarPath  Absolute path to the JAR file (dex2jar output)
     * @param classNames  Semicolon-separated list of fully-qualified class names
     *                    (from AndroidManifest's tachiyomi.extension.class)
     * @return List of loaded Sources
     */
    fun loadExtension(jarPath: String, classNames: String, nsfw: Boolean = false): List<Source> {
        val file = File(jarPath)
        if (!file.exists()) {
            throw IllegalArgumentException("Extension JAR not found: $jarPath")
        }

        val parentCl = this::class.java.classLoader
        val classLoader = classLoaders.getOrPut(jarPath) {
            URLClassLoader(arrayOf(file.toURI().toURL()), parentCl)
        }

        var names = classNames.split(";").map { it.trim() }.filter { it.isNotEmpty() }

        // Repos that publish prebuilt JARs give us no manifest, and some APKs
        // declare a class that does not exist. Fall back to scanning the JAR for
        // anything that actually implements Source/SourceFactory so the
        // extension still loads.
        if (names.isEmpty()) {
            names = scanForSourceClasses(file, classLoader)
            System.err.println("[ExtensionLoader] Scanned $jarPath: found ${names.size} candidate class(es)")
        }

        val results = mutableListOf<Source>()

        for (className in names) {
            val cacheKey = "$jarPath|$className"
            val existing = loadedByClass[cacheKey]
            if (existing != null) {
                results.addAll(existing)
                continue
            }

            try {
                val clazz = classLoader.loadClass(className)
                val newSources = instantiateSources(clazz)
                loadedByClass[cacheKey] = newSources
                for (instance in newSources) {
                    loadedSources[instance.id] = instance
                    nsfwFlags[instance.id] = nsfw
                    sourceJar[instance.id] = jarPath
                    results.add(instance)
                    System.err.println("[ExtensionLoader] Loaded: ${instance.name} (${instance.id}) from $className")
                }
            } catch (e: Throwable) {
                System.err.println("[ExtensionLoader] Failed to load $className: ${e.message}")
                e.printStackTrace(System.err)
                // Don't throw — continue loading remaining classes from this extension.
                // If ALL classes fail, the caller will get an empty list and can report that.
            }
        }

        return results
    }

    /**
     * Find entry-point classes inside a JAR without a manifest to point at them.
     *
     * Only top-level classes are considered, and inner/synthetic/abstract classes
     * are skipped, so the result is the set of concrete sources the extension
     * actually exposes. Classes are checked for assignability rather than loaded
     * eagerly, so a JAR full of helper classes is cheap to scan.
     */
    private fun scanForSourceClasses(jar: File, classLoader: URLClassLoader): List<String> {
        val factories = mutableListOf<String>()
        val sources = mutableListOf<String>()

        runCatching {
            JarFile(jar).use { archive ->
                for (entry in archive.entries()) {
                    val entryName = entry.name
                    if (!entryName.endsWith(".class")) continue
                    if (entryName.contains("$")) continue

                    val className = entryName.removeSuffix(".class").replace('/', '.')
                    if (isLibraryClass(className)) continue

                    val clazz = runCatching { classLoader.loadClass(className) }.getOrNull() ?: continue
                    if (clazz.isInterface) continue
                    if (java.lang.reflect.Modifier.isAbstract(clazz.modifiers)) continue

                    when {
                        SourceFactory::class.java.isAssignableFrom(clazz) -> factories.add(className)
                        Source::class.java.isAssignableFrom(clazz) -> sources.add(className)
                    }
                }
            }
        }.onFailure {
            System.err.println("[ExtensionLoader] Could not scan ${jar.name}: ${it.message}")
        }

        // A SourceFactory builds every variant the extension offers, so it wins
        // over the individual Source classes it instantiates. Keiyoushi emits one
        // `keiyoushi.source.Generated` factory per extension — note this lives
        // outside the `eu.kanade.tachiyomi.extension` package, so the scan must
        // not be restricted to it.
        return factories.ifEmpty { sources }
    }

    /** Bundled third-party code that can never be an extension entry point. */
    private fun isLibraryClass(className: String): Boolean = LIBRARY_PREFIXES.any {
        className.startsWith(it)
    }

    private val LIBRARY_PREFIXES = listOf(
        "kotlin.", "kotlinx.", "okhttp3.", "okio.", "org.jsoup.", "org.json.",
        "retrofit2.", "com.google.", "com.squareup.", "rx.", "io.reactivex.",
        "uy.kohesive.", "android.", "androidx.", "java.", "javax.",
        "org.intellij.", "org.jetbrains.",
    )

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

        // Try 4: Constructor(long) / Constructor(Long) — multi-source with source ID
        if (instance == null) {
            for (type in listOf(Long::class.javaPrimitiveType, java.lang.Long::class.java)) {
                if (type == null) continue
                try {
                    instance = clazz.getDeclaredConstructor(type).newInstance(0L)
                    break
                } catch (_: NoSuchMethodException) {}
            }
        }

        // Try 5: Constructor(String) — usually a language tag
        if (instance == null) {
            try {
                val ctor = clazz.getDeclaredConstructor(String::class.java)
                instance = ctor.newInstance("en")
                System.err.println(
                    "[ExtensionLoader] ${clazz.name} takes a String constructor arg; " +
                        "defaulted to \"en\". Multi-language variants of this source are not loaded."
                )
            } catch (_: NoSuchMethodException) {}
        }

        // Try 6: single-arg constructor of any other shape, with a null argument.
        if (instance == null) {
            val single = clazz.declaredConstructors.firstOrNull { it.parameterCount == 1 }
            if (single != null) {
                try {
                    single.isAccessible = true
                    instance = single.newInstance(null)
                } catch (_: Throwable) {}
            }
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

    /** Unload a single extension JAR and everything it registered. */
    fun unloadJar(jarPath: String): Int {
        val ids = sourceJar.filterValues { it == jarPath }.keys.toList()
        ids.forEach {
            loadedSources.remove(it)
            nsfwFlags.remove(it)
            sourceJar.remove(it)
        }
        loadedByClass.keys.removeIf { it.startsWith("$jarPath|") }
        classLoaders.remove(jarPath)?.close()
        return ids.size
    }

    /** Unload all extensions (cleanup) */
    fun unloadAll() {
        loadedSources.clear()
        loadedByClass.clear()
        nsfwFlags.clear()
        sourceJar.clear()
        classLoaders.values.forEach { it.close() }
        classLoaders.clear()
    }
}
