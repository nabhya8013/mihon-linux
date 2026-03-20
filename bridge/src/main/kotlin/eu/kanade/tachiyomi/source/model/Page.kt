package eu.kanade.tachiyomi.source.model

/**
 * Tachiyomi Page model stub.
 */
data class Page(
    val index: Int,
    val url: String = "",
    var imageUrl: String? = null,
) : java.io.Serializable {
    // Status tracking (used by the downloader)
    @Transient var status: Int = QUEUE
    @Transient var progress: Int = 0

    companion object {
        const val QUEUE = 0
        const val LOAD_PAGE = 1
        const val DOWNLOAD_IMAGE = 2
        const val READY = 3
        const val ERROR = 4
    }
}
