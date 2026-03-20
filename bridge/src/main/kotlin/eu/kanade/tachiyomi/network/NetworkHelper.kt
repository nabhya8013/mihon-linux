@file:Suppress("unused")
package eu.kanade.tachiyomi.network

import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.jsoup.Jsoup
import org.jsoup.nodes.Document
import rx.Observable
import rx.Subscriber
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * OkHttp helper functions that Tachiyomi extensions commonly use.
 */



/**
 * Convert an OkHttp Call to an RxJava 1 Observable.
 */
fun Call.asObservable(): Observable<Response> {
    return Observable.unsafeCreate { subscriber ->
        try {
            val response = execute()
            if (!subscriber.isUnsubscribed) {
                subscriber.onNext(response)
                subscriber.onCompleted()
            }
        } catch (e: Exception) {
            if (!subscriber.isUnsubscribed) {
                subscriber.onError(e)
            }
        }
    }
}

/**
 * Like asObservable() but throws on non-2xx status codes.
 */
fun Call.asObservableSuccess(): Observable<Response> {
    return asObservable().doOnNext { response ->
        if (!response.isSuccessful) {
            response.close()
            throw IOException("HTTP error ${response.code}")
        }
    }
}

/**
 * Parse an OkHttp Response body as a Jsoup Document.
 */
fun Response.asJsoup(html: String? = null): Document {
    return Jsoup.parse(html ?: body.string(), request.url.toString())
}

/**
 * Convenience Headers builder matching the pattern extensions use.
 */
fun Headers.Builder.add(name: String, lazyValue: () -> String): Headers.Builder {
    return add(name, lazyValue())
}


