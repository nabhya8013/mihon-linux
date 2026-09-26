# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project has not cut a
tagged release yet, so everything lives under **Unreleased**.

## [Unreleased]

### Added

- Library category management: create/edit/delete categories and bulk manga
  assignment (`e3451e3`).
- Advanced library controls: sort options, grid/list display modes, status/unread/
  downloaded filters, batch actions, and per-category persisted preferences
  (`4ad2f20`). Behavior contract: `docs/specs/library-controls.md`.
- `.tachibk` Android backup import (*More → Data*) — restores manga, categories, and
  chapter metadata without an external protobuf dependency.
- Anti-bot foundation: `curl_cffi` HTTP backend with a Chrome TLS fingerprint,
  WebKit challenge-solver window, persistent cookie jar shared with the JVM bridge,
  per-domain User-Agent synchronization, and an OkHttp `CloudflareInterceptor` in
  the bridge.
- JVM extension bridge: JSON-RPC 2.0 process loading Tachiyomi/Mihon APK extensions,
  with `android.*` compatibility stubs and JSON-RPC routing (`d911584`).
- Library update system and **Updates** tab — scans the library, fetches latest
  chapters per source, records new chapters, recalculates unread counts (`b0f983a`).
- Reading history improvements and reader navigation/UI refinements (`ad2685f`).
- Extension catalog browsing in Browse → Extensions: search the configured
  repositories (Keiyoushi by default), install, and see update badges.
- Per-source preferences and source-defined search filters exposed over the
  bridge.
- Central logging configuration writing to `~/.local/share/mihon-linux/logs/`.

### Changed

- HTTP call sites (`downloader`, `image_loader`, `mangadex`, `allmanga`) now go
  through the shared `mihon.core.http_client` session factory; `requests` is only a
  fallback backend.
- README rewritten: virtualenv-based install, distro-correct `JAVA_HOME`,
  repo-relative build paths, accurate feature list, troubleshooting section.
- Docs reorganized under `docs/` (`library-controls` spec, `parity-workflow`).
- Third-party APK/JAR extensions now load and run: entry-point discovery by
  archive scan, suspend-API dispatch, the interceptor chain extensions-lib
  asserts on, a Rhino-backed JS engine, and the Android stubs sources reach.
  Measured on a 14-source sample: 0 could fetch a chapter before, 7 now run the
  full popular → search → details → chapters → pages → image chain.
- Uninstalling an extension removes its files instead of only unregistering it
  in memory.
- Built-in sources reduced to MangaDex and AllManga; the MangaFire stub was
  never functional and is no longer registered.

### Pending

- `LICENSE` file — license not yet chosen (Apache 2.0 recommended to match upstream
  Mihon/Tachiyomi).
