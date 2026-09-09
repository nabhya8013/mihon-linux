@file:Suppress("unused")
package android.os

/**
 * android.os.Build stub. Extensions branch on SDK_INT for WebView/crypto quirks;
 * report a recent API level so they take the modern path.
 */
object Build {
    const val MANUFACTURER: String = "Mihon"
    const val MODEL: String = "Linux"
    const val DEVICE: String = "desktop"
    const val BRAND: String = "mihon"
    const val PRODUCT: String = "mihon-linux"

    object VERSION {
        /** Android 14. Matches what Mihon targets, so extensions take modern branches. */
        @JvmField
        val SDK_INT: Int = 34
        @JvmField
        val RELEASE: String = "14"
    }

    object VERSION_CODES {
        const val LOLLIPOP = 21
        const val M = 23
        const val N = 24
        const val O = 26
        const val P = 28
        const val Q = 29
        const val R = 30
        const val S = 31
        const val TIRAMISU = 33
        const val UPSIDE_DOWN_CAKE = 34
    }
}
