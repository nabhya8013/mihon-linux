package eu.kanade.tachiyomi.network.interceptor

import java.net.URI
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.exists
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody

/**
 * CloudflareInterceptor — the bridge-side counterpart of Mihon Android's
 * `CloudflareInterceptor`. When an OkHttp request comes back with an
 * anti-bot status code (403/503), this interceptor:
 *
 * 1. Writes a `challenge_request.json` file describing the blocked URL
 *    into a directory shared with the Python UI process.
 * 2. Polls the directory for a matching `challenge_response_<id>.json`
 *    file that the Python solver writes after the user has solved the
 *    challenge (WebKitGTK browser cookie + User-Agent extraction).
 * 3. Reads the solved cookies / User-Agent from the response file,
 *    applies them to the original request, and retries once.
 * 4. Falls back to returning the original blocked response if the
 *    solver does not respond within the timeout.
 *
 * The handshake is intentionally file-based because the bridge IPC
 * (JSON-RPC over stdin/stdout) only flows from Python to JVM. Asking
 * the JVM to send a request back through the bridge would deadlock
 * the calling thread.
 */
class CloudflareInterceptor(
    private val challengeDir: Path? = System.getenv("MIHON_CHALLENGE_DIR")
        ?.takeIf { it.isNotBlank() }
        ?.let { Path.of(it) },
    private val cookieJar: Path? = System.getenv("MIHON_COOKIE_JAR")
        ?.takeIf { it.isNotBlank() }
        ?.let { Path.of(it) },
    private val timeoutMs: Long = 60_000L,
    private val pollIntervalMs: Long = 250L,
    private val sleeper: (Long) -> Unit = { Thread.sleep(it) },
    private val clock: () -> Long = { System.currentTimeMillis() },
) : Interceptor {

    private val json = Json { ignoreUnknownKeys = true; prettyPrint = true }

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val response = chain.proceed(request)
        if (response.code !in ANTI_BOT_CODES) {
            return response
        }
        if (challengeDir == null) {
            return response
        }

        val solved = runSolverHandshake(request.url.toString(), response.code)
        response.close()
        if (!solved) {
            // Construct a fresh 403 response without re-issuing the request.
            // Re-proceeding here would risk an infinite loop if the source
            // still returns an anti-bot response without solved cookies.
            return Response.Builder()
                .request(request)
                .protocol(response.protocol)
                .code(response.code)
                .message(response.message)
                .body("".toResponseBody(null))
                .build()
        }

        val newHeaders = readSolvedHeaders(request.url.toString())
        val retryRequest = request.newBuilder().apply {
            val ua = newHeaders.userAgent
            if (!ua.isNullOrBlank()) {
                header("User-Agent", ua)
            }
            val cookie = newHeaders.cookieHeader
            if (!cookie.isNullOrBlank()) {
                header("Cookie", cookie)
            }
        }.build()
        return chain.proceed(retryRequest)
    }

    private fun runSolverHandshake(url: String, statusCode: Int): Boolean {
        val dir = challengeDir ?: return false
        if (!ensureDir(dir)) return false
        val requestId = "cf-${clock()}-${Thread.currentThread().id}"
        val requestPath = dir.resolve("challenge_request.json")
        val responsePath = dir.resolve("challenge_response_$requestId.json")

        val payload = ChallengeRequestPayload(
            request_id = requestId,
            url = url,
            status_code = statusCode,
            timeout_ms = timeoutMs,
        )
        return try {
            Files.writeString(requestPath, json.encodeToString(payload))
            waitForResponse(responsePath)
        } catch (e: Exception) {
            System.err.println("[CloudflareInterceptor] handshake failed: ${e.message}")
            false
        }
    }

    private fun waitForResponse(responsePath: Path): Boolean {
        val deadline = clock() + timeoutMs
        while (clock() < deadline) {
            if (responsePath.exists()) {
                return try {
                    val payload = json.decodeFromString<ChallengeResponsePayload>(
                        Files.readString(responsePath),
                    )
                    payload.solved
                } catch (e: Exception) {
                    System.err.println("[CloudflareInterceptor] bad response file: ${e.message}")
                    false
                } finally {
                    runCatching { Files.deleteIfExists(responsePath) }
                }
            }
            sleeper(pollIntervalMs)
        }
        return false
    }

    private fun readSolvedHeaders(url: String): SolvedHeaders {
        val jar = cookieJar ?: return SolvedHeaders()
        if (!jar.exists()) return SolvedHeaders()
        val payload = runCatching {
            json.decodeFromString<SharedCookieJar>(Files.readString(jar))
        }.getOrNull() ?: return SolvedHeaders()

        val host = runCatching { URI(url).host?.lowercase() }.getOrNull() ?: return SolvedHeaders()
        val cookieHeader = payload.cookies
            .filter { record ->
                (host == record.domain || host.endsWith(".${record.domain}")) &&
                    (!record.secure || url.startsWith("https", ignoreCase = true))
            }
            .joinToString("; ") { "${it.name}=${it.value}" }
            .takeIf { it.isNotEmpty() }

        val userAgent = payload.user_agents
            .filter { host == it.domain || host.endsWith(".${it.domain}") }
            .maxByOrNull { it.domain.length }
            ?.user_agent
            ?.takeIf { it.isNotBlank() }

        return SolvedHeaders(cookieHeader = cookieHeader, userAgent = userAgent)
    }

    private fun ensureDir(dir: Path): Boolean = try {
        Files.createDirectories(dir)
        true
    } catch (e: Exception) {
        System.err.println("[CloudflareInterceptor] cannot create challenge dir: ${e.message}")
        false
    }

    private data class SolvedHeaders(
        val cookieHeader: String? = null,
        val userAgent: String? = null,
    )

    @Serializable
    private data class ChallengeRequestPayload(
        val request_id: String,
        val url: String,
        val status_code: Int,
        val timeout_ms: Long,
    )

    @Serializable
    private data class ChallengeResponsePayload(
        val request_id: String,
        val solved: Boolean,
    )

    @Serializable
    private data class SharedCookieJar(
        val version: Int = 1,
        val cookies: List<SharedCookieRecord> = emptyList(),
        val user_agents: List<SharedUserAgentRecord> = emptyList(),
    )

    @Serializable
    private data class SharedCookieRecord(
        val domain: String,
        val path: String = "/",
        val name: String,
        val value: String,
        val secure: Boolean = false,
        val updated_at: Double = 0.0,
    )

    @Serializable
    private data class SharedUserAgentRecord(
        val domain: String,
        val user_agent: String,
        val updated_at: Double = 0.0,
    )

    companion object {
        val ANTI_BOT_CODES: Set<Int> = setOf(403, 503)
    }
}
