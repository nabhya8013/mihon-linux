package eu.kanade.tachiyomi.network.interceptor

import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.exists
import okhttp3.Interceptor
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

/**
 * Unit tests for the JVM CloudflareInterceptor.
 *
 * The interceptor's solver handshake is a file-based protocol. The
 * tests here drive it with a fake solver that simply writes the
 * response file directly, then verify the request is retried with
 * the persisted cookie and User-Agent from the shared jar.
 */
class CloudflareInterceptorTest {

    @TempDir
    lateinit var tmp: Path

    private lateinit var cookieJar: Path
    private lateinit var challengeDir: Path
    private val fakeSleeperCalls = mutableListOf<Long>()
    private var fakeNow: Long = 1_000_000L

    @BeforeEach
    fun setUp() {
        cookieJar = tmp.resolve("cookies.json")
        challengeDir = tmp.resolve("challenges")
        Files.createDirectories(challengeDir)
    }

    @AfterEach
    fun tearDown() {
        fakeSleeperCalls.clear()
    }

    @Test
    fun `passes through 2xx responses without handshake`() {
        val interceptor = buildInterceptor()
        val chain = FakeChain(
            Request.Builder().url("https://example.test/ok").build(),
            responseCode = 200,
            responseBodies = listOf("ok"),
        )

        val response = interceptor.intercept(chain)

        assertEquals(200, response.code)
        assertEquals(1, chain.callCount)
        assertTrue(!Files.exists(challengeDir.resolve("challenge_request.json")))
    }

    @Test
    fun `403 triggers handshake and retries with solved cookies and UA`() {
        val interceptor = buildInterceptor(
            cookieRecords = listOf(
                TestCookie("example.test", "cf_clearance", "ok", secure = true),
            ),
            userAgents = listOf(
                TestUserAgent("example.test", "SolvedUA"),
            ),
        )
        val chain = FakeChain(
            Request.Builder().url("https://example.test/protected").build(),
            responseCode = 403,
            responseBodies = listOf("blocked", "unblocked"),
        )
        launchSolverAfterDelay(delayMs = 50)

        val response = interceptor.intercept(chain)

        assertEquals(200, response.code)
        assertEquals(2, chain.callCount)
        val retried = chain.requests.last()
        assertEquals("SolvedUA", retried.header("User-Agent"))
        val cookieHeader = retried.header("Cookie")
        assertNotNull(cookieHeader)
        assertTrue(cookieHeader!!.contains("cf_clearance=ok"))
    }

    @Test
    fun `falls back to synthetic 403 when no solver response arrives`() {
        val interceptor = buildInterceptor(solverWillRespond = false, timeoutMs = 200)
        val chain = FakeChain(
            Request.Builder().url("https://example.test/protected").build(),
            responseCode = 403,
            responseBodies = listOf("blocked"),
            retryResponseCode = 403,
        )

        val response = interceptor.intercept(chain)

        // Falls back without issuing a second request, avoiding loops
        assertEquals(403, response.code)
        assertEquals(1, chain.callCount)
    }

    @Test
    fun `503 also triggers handshake`() {
        val interceptor = buildInterceptor()
        val chain = FakeChain(
            Request.Builder().url("https://example.test/protected").build(),
            responseCode = 503,
            responseBodies = listOf("blocked", "ok"),
        )
        // No jar entries -> retry will still happen but without cookies/UA headers
        launchSolverAfterDelay(delayMs = 30)

        interceptor.intercept(chain)
        assertEquals(2, chain.callCount)
    }

    @Test
    fun `non anti-bot status codes are passed through without handshake`() {
        val interceptor = buildInterceptor()
        val chain = FakeChain(
            Request.Builder().url("https://example.test/redirect").build(),
            responseCode = 404,
            responseBodies = listOf("not found"),
        )

        interceptor.intercept(chain)
        assertEquals(1, chain.callCount)
        assertTrue(!Files.exists(challengeDir.resolve("challenge_request.json")))
    }

    // ── Helpers ───────────────────────────────────────────────────────────

    private fun buildInterceptor(
        cookieRecords: List<TestCookie> = emptyList(),
        userAgents: List<TestUserAgent> = emptyList(),
        solverWillRespond: Boolean = true,
        timeoutMs: Long = 5_000L,
    ): CloudflareInterceptor {
        writeJar(cookieRecords, userAgents)
        return CloudflareInterceptor(
            challengeDir = challengeDir,
            cookieJar = cookieJar,
            timeoutMs = timeoutMs,
            pollIntervalMs = 10L,
            // The fake clock only advances when the interceptor sleeps. Without
            // this the deadline check never fires and the "no solver response"
            // case loops forever. The real sleep is capped so the polling loop
            // still yields to the solver thread without costing wall-clock time.
            sleeper = { ms ->
                fakeSleeperCalls.add(ms)
                fakeNow += ms
                Thread.sleep(minOf(ms, 5L))
            },
            clock = { fakeNow },
        )
    }

    private fun writeJar(cookies: List<TestCookie>, userAgents: List<TestUserAgent>) {
        val payload = buildString {
            append("{")
            append("\"version\":1,")
            append("\"cookies\":[")
            append(cookies.joinToString(",") {
                val secure = if (it.secure) "true" else "false"
                "{\"domain\":\"${it.domain}\",\"path\":\"/\",\"name\":\"${it.name}\"," +
                    "\"value\":\"${it.value}\",\"secure\":$secure,\"updated_at\":1.0}"
            })
            append("],")
            append("\"user_agents\":[")
            append(userAgents.joinToString(",") {
                "{\"domain\":\"${it.domain}\",\"user_agent\":\"${it.userAgent}\",\"updated_at\":1.0}"
            })
            append("]")
            append("}")
        }
        Files.writeString(cookieJar, payload)
    }

    private fun launchSolverAfterDelay(delayMs: Long) {
        Thread {
            Thread.sleep(delayMs)
            val requestPath = challengeDir.resolve("challenge_request.json")
            val idPattern = Regex("\"request_id\"\\s*:\\s*\"([^\"]+)\"")
            // Wait until a complete request can be read. Like the real solver,
            // treat an unreadable file as "not yet" rather than giving up: a
            // single read that fails would otherwise strand the interceptor
            // until its timeout.
            val deadline = System.currentTimeMillis() + 5_000
            var id: String? = null
            while (id == null && System.currentTimeMillis() < deadline) {
                id = runCatching { idPattern.find(Files.readString(requestPath))?.groupValues?.get(1) }
                    .getOrNull()
                if (id == null) Thread.sleep(5)
            }
            if (id != null) {
                val responsePath = challengeDir.resolve("challenge_response_$id.json")
                val tmp = challengeDir.resolve("challenge_response_$id.json.tmp")
                Files.writeString(tmp, "{\"request_id\":\"$id\",\"solved\":true}")
                Files.move(tmp, responsePath, java.nio.file.StandardCopyOption.ATOMIC_MOVE)
            }
        }.also { it.isDaemon = true }.start()
    }

    private data class TestCookie(
        val domain: String,
        val name: String,
        val value: String,
        val secure: Boolean,
    )

    private data class TestUserAgent(
        val domain: String,
        val userAgent: String,
    )

    /**
     * @param responseCode status returned for the first call.
     * @param retryResponseCode status for every call after the first. Defaults
     *   to 200 so a solved challenge actually unblocks; returning the blocked
     *   code forever would make the retry indistinguishable from a failure.
     */
    private class FakeChain(
        private val originalRequest: Request,
        private val responseCode: Int,
        responseBodies: List<String>,
        private val retryResponseCode: Int = 200,
    ) : Interceptor.Chain {
        private val bodies = responseBodies
        val requests: MutableList<Request> = mutableListOf()
        private var index = 0
        var callCount: Int = 0
            private set

        init {
            requests.add(originalRequest)
        }

        override fun request(): Request = requests.last()

        override fun proceed(request: Request): Response {
            callCount += 1
            val body = bodies.getOrNull(index) ?: ""
            val code = if (index == 0) responseCode else retryResponseCode
            index += 1
            if (request !== originalRequest) {
                requests.add(request)
            }
            return Response.Builder()
                .request(request)
                .protocol(Protocol.HTTP_1_1)
                .code(code)
                .message("test")
                .body(body.toResponseBody())
                .build()
        }

        override fun connection() = null
        override fun call() = throw UnsupportedOperationException()
        override fun connectTimeoutMillis() = 0
        override fun withConnectTimeout(timeout: Int, unit: java.util.concurrent.TimeUnit) = this
        override fun readTimeoutMillis() = 0
        override fun withReadTimeout(timeout: Int, unit: java.util.concurrent.TimeUnit) = this
        override fun writeTimeoutMillis() = 0
        override fun withWriteTimeout(timeout: Int, unit: java.util.concurrent.TimeUnit) = this
    }
}
