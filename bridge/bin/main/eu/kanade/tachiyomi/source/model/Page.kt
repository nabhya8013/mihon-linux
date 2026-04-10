package eu.kanade.tachiyomi.source.model

import android.net.Uri

/**
 * Tachiyomi Page model stub.
 * Extensions construct pages with (index, url, imageUrl, uri) parameters.
 */
data class Page(
    val index: Int,
    val url: String = "",
    var imageUrl: String? = null,
    var uri: Uri? = null,
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
