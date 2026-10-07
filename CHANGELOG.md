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
- `.tachibk` Android backup import, now under *More → Backup and Restore* — restores
  manga, categories, chapters, read progress and history; the protobuf schema is
  built at runtime, so `protoc` is not needed.
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
- MIT `LICENSE`, `NOTICE` crediting Mihon/Tachiyomi, GitHub Actions CI and release
  workflows, and Flatpak packaging.
- `.tachibk` export alongside import, using upstream-compatible source IDs.
- *More → Backup and Restore* page: restore previews the file first, offers Merge
  or Overwrite for manga already present, and shows progress.
- Disk-backed page cache (512 MB bound) and cover cache, with a prefetch window,
  landscape spread detection, and seamless webtoon stitching in the reader.
- Local source: CBZ/ZIP archives and image folders, plus CBR/RAR via the optional
  `rarfile` package and an unrar-compatible tool.
- Tracking: AniList and MyAnimeList OAuth, two-way sync, 85% read-progress
  threshold, retry queue, and keyring token storage.
- Global search across all sources in parallel, with per-source results and timeout.
- Source filter sheet built from Tachiyomi `FilterList`.
- Library presenter, toast notifications, and desktop notifications for
  background events.
- Keyboard shortcuts (`Ctrl+K`, `Ctrl+R`/`F5`, `Ctrl+1`–`Ctrl+5`, `Ctrl+?`) and
  drag and drop for APK install and category reorder.
- Download queue controls: cancel, retry, remove, reorder, and move to front;
  configurable download location and worker count.
- Refresh button on the manga page to fetch details and chapters on demand.
- Reader direction is remembered per series; changing it in the reader no longer
  changes the default for every other series. *Use Default* clears it.
- Backups carry AniList/MyAnimeList links and each series' reading mode in both
  directions, using Android Mihon's tracker ids, status codes and score scales.
- Upcoming view in the Updates tab: next-chapter predictions from each series'
  release rhythm, grouped by day.
- Incognito mode (*More*): reading records no history, page, read mark or tracker
  update while it is on.
- Tracker pull after scheduled library updates, so changes made on AniList or
  MyAnimeList arrive without opening each manga (*More → Tracking*, on by default).
- Reader: tap-zone layouts (Standard, Kindle, Edges, Off), optional scroll-wheel
  page turns, an end-of-chapter card before moving to the next chapter, a loading
  spinner shown only for pages that are not cached, webtoon side padding, and
  keys for Page Up/Down, Backspace, Home/End, zoom (`+`/`-`/`0`) and fullscreen
  (`F`/`F11`).
- Scheduled background library updates (Smart Updates), with per-category
  exclusion.
- Checkbox multi-select for chapter batch actions.
- System/Light/Dark appearance setting.
- Notification of tracker retry queue results at startup.

### Changed

- CI and release workflows moved to the Node 24 versions of their actions
  (`checkout@v7`, `setup-python@v7`, `setup-java@v6`, `cache@v6`,
  `upload-artifact@v7`, `action-gh-release@v3`) ahead of Node 20's removal.

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
- The *More* panel is split into dedicated Settings pages: Reader, Appearance,
  Library, Downloads and Data, Sources, Tracking, About.
- Registered sources are filtered to English by default.
- App icon replaced with the new circular logo.

### Fixed

- MangaDex, AllManga and MangaFire now record the source's chapter order, so the
  *Source order* sort and next/previous chapter place unnumbered chapters correctly.

- Reader, webtoon mode: reading progress, history and tracker updates are now saved
  as you scroll (previously only when the chapter ended), and a chapter reopens at
  the saved strip instead of the top.
- Reader, webtoon mode: strips load in a window around the one being read and
  release their images when far away, instead of loading the whole chapter at once.
  Each strip is sized from its own aspect ratio, so short strips are no longer
  padded to 800 px and strips meet without seams. Downloaded chapters now load in
  webtoon mode too.
- Reader: the zoom control now zooms. Fit-width shows the page at full width and
  scrolls, instead of stretching it to the window height.
- Reader: page-turn taps no longer block the mouse wheel or dragging; a click that
  turns into a drag does not turn the page.
- Reader: next chapter follows the source's chapter order, so unnumbered chapters
  are no longer skipped. Previous/next chapter buttons and `N`/`P` keys were added.
- The Flatpak manifest now builds and runs: it targets the GNOME 50 runtime (47 is
  end-of-life), installs a sandbox launcher instead of the development `mihon.sh`,
  keeps the `mihon` package directory when copying, and pins all 56 Python
  dependency wheels by hash. A new workflow builds it in CI.
- The manga page showed no description, author or genres when opened from Browse or
  search, even after the details call succeeded: the labels were only filled from
  the listing. They now refresh when details arrive.
- Opening a manga waited on the network for the chapter list every time. Saved
  chapters now show immediately and the source is contacted only when the copy is
  missing or stale (details after 24 hours, chapters after 1 hour). Library updates
  count as a chapter fetch.
- Opening a manga from Browse refetched details that were already stored.
- `.tachibk` import now restores chapters, read progress, and reading history. It
  previously wrote only manga and categories, so every chapter came back unread.
- Corrupt, empty, or non-backup files are rejected with a clear message instead of
  a stack trace or a silent no-op.
- MangaFire crash, AllAnime auth, and a dead logger.
- Dead Settings controls in the More panel are wired up.
- A local cover cache path is no longer passed to the HTTP fetcher.
- CI dependency install and missing `gi`/`protobuf` in the Python tests.
