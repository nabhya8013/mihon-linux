# Mihon JVM Bridge

Standalone Kotlin process that loads Tachiyomi/Mihon `.apk` extensions and exposes
them to the Python app over **JSON-RPC 2.0 on stdin/stdout**. It reimplements the
slice of the Android runtime that extensions expect (stub `android.*` classes, a
`NetworkHelper`/OkHttp stack, Jsoup helpers, Injekt DI).

The Python side lives in `mihon/extensions/jvm_bridge.py` (process management) and
`mihon/extensions/jvm_proxy.py` (per-source proxy objects).

## Build

```bash
cd bridge
JAVA_HOME=$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")") ./gradlew jar
```

Needs JDK 21 (not just a JRE). Output: `build/libs/mihon-bridge-1.0-SNAPSHOT.jar`,
run as `java -jar …` by `JVMBridgeManager`.

Common `JAVA_HOME` locations: Fedora `/usr/lib/jvm/java-21-openjdk`,
Debian/Ubuntu `/usr/lib/jvm/java-21-openjdk-amd64`.

## Protocol

- One JSON-RPC request per line on **stdin**, one response per line on **stdout**.
- **stderr** carries human-readable logging only.
- On startup the bridge emits a notification:
  `{"jsonrpc":"2.0","method":"bridge.ready","params":{"version":"1.0.0"}}`.
- Plain-text `exit` or `quit`, or closing stdin (EOF), shuts it down.

### Methods (`org/mihon/bridge/JsonRpcRouter.kt`)

| Method | Purpose |
|---|---|
| `extension.load` | Load an extension JAR, register its sources |
| `extension.list` | List loaded sources |
| `extension.unload` | Unload all sources |
| `extension.popular` / `extension.latest` / `extension.search` | Manga listing (paged) |
| `extension.details` | Full manga metadata |
| `extension.chapters` | Chapter list for a manga |
| `extension.pages` | Page image URLs for a chapter |
| `extension.filters` | Source's `FilterList` (genre/sort/status UI model) |
| `system.ping` | Liveness — `{pong, timestamp}` |
| `system.status` | Loaded-extension count, JVM version, memory |
| `system.version` | Bridge / protocol / Java / Kotlin versions |

Not yet implemented: `extension.preferences`, `extension.image`, `extension.login`.

## Environment contract

`JVMBridgeManager.start` passes these to the JVM process:

| Var | Meaning |
|---|---|
| `JAVA_HOME` | JDK used to launch the bridge |
| `MIHON_COOKIE_JAR` | Path to the shared `cookies.json` (site cookies + per-domain User-Agent), read/written by both Python and the bridge's `CookieManager` / `SyncedUserAgentInterceptor` |
| `MIHON_CHALLENGE_DIR` | Directory where the `CloudflareInterceptor` drops `challenge_request.json` and waits for `challenge_response_<id>.json` written by the Python `ChallengeSolverBridge` |

## Android stub coverage

`src/main/kotlin/android/…` and friends: `app.Application`, `content.Context`,
`content.SharedPreferences`, `graphics.Bitmap`, `net.Uri`, `os.Bundle`,
`text.TextUtils`, `util.Base64`, `util.Log`, `webkit.CookieManager`,
`androidx.preference.PreferenceScreen`, `app.cash.quickjs.QuickJs`, plus Injekt
(`uy.kohesive.injekt`). Network layer under
`eu.kanade.tachiyomi.network` (Cloudflare + rate-limit interceptors) and source
model/base classes under `eu.kanade.tachiyomi.source`.

Known gaps: `android.text.format.DateFormat`, a `kotlin.coroutines` bridge for
`suspend` source APIs.

## Tests

```bash
./gradlew test          # JUnit — CloudflareInterceptorTest
scripts/verify_slice5.sh  # from repo root: compile + test + jar + python tests
```
