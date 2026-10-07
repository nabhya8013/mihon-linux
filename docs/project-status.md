# Project Status

What Mihon Linux can do today, how it got here, and what is still open.

*As of 7 October 2026, branch `feature/next` at `a79c598`, 53 commits.*

## At a glance

| | |
|---|---|
| App | Native GTK4 / Libadwaita manga reader, Python, about 18,000 lines |
| Extension bridge | Kotlin JSON-RPC process for Tachiyomi/Mihon APK extensions, about 4,500 lines |
| Built-in sources | MangaDex, AllManga, MangaFire, and a Local source for your own files |
| Third-party sources | APK extensions from Keiyoushi or any configured repository, through the bridge |
| Tests | 474 Python tests across 28 files, plus Kotlin tests for the bridge |
| CI | Tests, lint, desktop metadata checks, bridge build, and a Flatpak build |
| Packaging | Flatpak (GNOME 50), desktop entry, AppStream metadata, MIT license |

## Timeline

| Period | What landed |
|---|---|
| March 2026 | First version: library, browse, reader, history. The JVM bridge starts on its own branch. |
| April 2026 | Bridge merged with Android compatibility stubs and JSON-RPC routing. Updates tab, auto-update on startup, WebView support, advanced library controls (sort, filter, display modes, batch actions). |
| August 2026 | Category management and bulk assignment. |
| September 2026 | Real APK extensions run end to end. Extension repositories. Anti-bot layer. `.tachibk` import and export. Page and cover caching. AniList and MyAnimeList tracking. Local source with CBR/RAR. Global search. Download queue controls. Scheduled library updates. Appearance setting. Settings split into pages. New icon. CI, license and Flatpak metadata. |
| 7 October 2026 | Docs brought in line with the code. Backup and Restore page, with a fix for restores losing all read progress. Chapter and details caching. A Flatpak that builds and runs, built in CI. A flaky bridge test fixed at its root. Seven reader bugs fixed. |

## What is built

### Library

- Categories with create, rename, delete, reorder (buttons or drag and drop) and bulk assignment.
- Per-category sort, filter (status, unread, downloaded) and display (grid or list), saved across restarts. The behaviour is specified in [`specs/library-controls.md`](specs/library-controls.md).
- Batch actions on selected manga, and unread badges.
- State lives in a presenter (`mihon/ui/library_presenter.py`) that is tested without GTK.

### Sources and extensions

- **Built-in sources:** MangaDex, AllManga and MangaFire, plus the Local source.
- **Local source:** reads one folder per series. Chapters are CBZ/ZIP archives or folders of images, with CBR/RAR when the optional `rarfile` package and an unrar tool are installed. Covers come from a `cover` image or the first page. An optional `details.json` overrides the metadata.
- **APK extensions:** the Kotlin bridge (`bridge/`) loads Tachiyomi/Mihon extensions and answers popular, latest, search, details, chapters, pages, filters and preferences calls. On a 14-extension sample, 7 ran the full chain from listing to image.
- **Repositories:** Browse → Extensions lists, installs and updates extensions from configured repositories (Keiyoushi by default), with icons and update badges. Repositories are managed under *More → Sources*.
- **Filters:** a source's Tachiyomi `FilterList` becomes a native GTK filter sheet.
- **Language:** sources are filtered to English by default.

### Anti-bot layer

- HTTP goes through `curl_cffi` with a real Chrome TLS fingerprint; `requests` is only a fallback.
- A WebKit window solves Cloudflare and DDoS-Guard challenges. The cookies and User-Agent it gets are stored in a jar shared with the JVM bridge.
- The bridge has its own `CloudflareInterceptor` that hands challenges to the same solver through a file handshake. Request files are now written atomically.

### Manga page

- Details, chapter list with three sort modes (number, source order, upload date), filters and search.
- Checkbox multi-select for batch actions on chapters.
- **Caching:** saved chapters show immediately. The source is contacted only when needed: details when never fetched or older than 24 hours, chapters when missing or older than 1 hour. A library update counts as a chapter fetch. The Local source always rereads its folder. The rules are in `mihon/core/fetch_policy.py`.
- A **Refresh** button forces a fetch and reports failures. Background refresh failures are only logged, because the saved copy is already shown.
- WebView, tracking and migration actions.

### Reader

- **Paged mode:** single, double or auto layout (double at 1600 px wide and above), right to left or left to right. Landscape scans (wider than 1.3:1) are detected and shown as full spreads.
- **Sizing:** fit page or fit width. Fit width shows the page at full width and scrolls. Zoom from 30% to 300% resizes the page in place. Page sizes come from `mihon/core/reader_logic.py`.
- **Prefetch:** pages 3 ahead and 2 behind are loaded in advance, so a page turn is instant.
- **Webtoon mode:**
  - Strips are stacked with no gaps, each sized from its own aspect ratio.
  - Only strips near the one being read hold an image, which keeps long chapters light on memory.
  - Progress, history and tracker updates are saved as you scroll.
  - A chapter reopens at the strip you left.
- **Taps:** four layouts. Standard uses the left and right thirds to turn pages and the middle for the menu. Kindle puts the menu along the top third. Edges turns pages only from narrow side strips. Off makes every click open the menu. All are direction-aware with an invert option, and none block scrolling or dragging.
- **Scroll wheel:** optionally turns pages in paged mode. A tall page scrolls first, and the page turns only once you scroll past its end. One wheel gesture turns one page.
- **Loading spinner:** appears only when a page takes longer than 150 ms, so turning through cached pages never flashes it.
- **End of chapter:** a card shows the chapter just finished and the next one. One more "next" (click, key or button) opens it; "previous" or **Stay** keeps reading.
- **Webtoon side padding:** 0–50% of the window left empty at the sides, so strips do not stretch across a wide window.
- **Keys:** arrows or `A`/`D` turn pages, `Page Up`/`Page Down` and `Space` scroll or page, `Backspace` goes back, `Home`/`End` jump to the first or last page, `N`/`P` change chapter, `+`/`-`/`0` zoom, `F`/`F11` toggle fullscreen, `Esc` closes.
- **Chapters:** next and previous follow the source's own chapter order, so unnumbered chapters are not skipped. Buttons in the top bar, or `N` and `P`.
- **Other settings:** background colour, crop borders, page slider, fullscreen, keep screen on.
- **Downloads:** downloaded chapters are read from disk in both modes.

### Updates, downloads and history

- **Updates tab:** checks every library manga, records new chapters, and recalculates unread counts.
- **Scheduled updates:** run on startup and every 6, 12 or 24 hours. They can skip dropped series and excluded categories, and post a desktop notification.
- **Download queue:** cancel, retry, remove, reorder and move to front, with configurable location and number of parallel downloads.
- **History tab:** recently read chapters.

### Tracking

- AniList (implicit grant) and MyAnimeList (PKCE). You register your own client ID, and no secret is needed.
- Reading past 85% of a chapter updates the tracker. Failed updates are queued with backoff and retried at startup, which reports the results.
- Status, progress and score can be edited from the manga page, with a pull to refresh from the tracker.
- Tokens are kept in the system keyring through libsecret, with a clearly flagged database fallback.

### Backup and Restore

- *More → Backup and Restore* exports a `.tachibk` that Android Mihon can restore, and imports one from Android or from this app.
- **Preview:** shows manga, chapters, chapters read, and how many manga already exist, before anything is written.
- **Merge or Overwrite** for manga you already have. Merge keeps your data and never turns read chapters back to unread. Overwrite takes the backup's details and progress. Neither removes manga or chapters.
- **What is restored:** chapters, read progress, categories and history, with a progress bar. Restoring the same file twice adds nothing.
- **Bad files:** corrupt, empty or non-backup files are rejected with a clear message.
- **Source IDs:** use upstream's hashing, so backups move in both directions.

### Search and migration

- Global search (`Ctrl+K` or `/`) queries every source in parallel and shows each source's results as they arrive, with a 10-second limit per source.
- The same search moves a manga from one source to another.

### Settings and desktop integration

- **Settings pages:** Reader, Appearance, Library, Downloads and Data, Backup and Restore, Sources, Tracking, About.
- **Appearance:** System, Light or Dark.
- **Notifications:** toasts inside the app, desktop notifications for background events.
- **Keyboard shortcuts:** `Ctrl+1`–`Ctrl+5` tabs, `Ctrl+R`/`F5` refresh, `Ctrl+W` back, `Ctrl+?` for the full list.
- **Drag and drop:** drop an APK on the Extensions tab to install it.
- **Desktop files:** `.desktop` entry, scalable and symbolic icons, and AppStream metadata that passes `appstreamcli validate`.

### Packaging and CI

- **Flatpak:** builds and runs on the GNOME 50 runtime. All 56 Python dependency wheels are pinned by hash in `data/python3-requirements.json`, and a test fails if they drift from `requirements.txt`. The sandbox has no JDK, so APK extensions are not available in the Flatpak.
- **CI on every push:**
  - Python tests under a virtual display.
  - An import check of every module.
  - `ruff` at error level.
  - `desktop-file-validate` and `appstreamcli validate`.
  - Gradle build and tests of the bridge.
- **Flatpak workflow:** builds in the Flathub GNOME 50 container, checks that the dependencies import inside the sandbox, and uploads the bundle as an artifact.
- **Releases:** tagging `v*` builds a release with a generated changelog.

## Recent work in detail (7 October 2026)

Each item was checked in a real application window as well as by unit tests.

| Commit | Change | What it fixed |
|---|---|---|
| `c60d0ec` | Docs sync | The changelog, README and parity table described features as missing that had shipped, and gave wrong menu paths. |
| `d04f4e7` | Backup and Restore page | `.tachibk` import wrote only manga and categories, so every restored chapter came back unread. Restores also never refreshed unread counts. |
| `abaff5c` | Chapter and details caching | Opening a manga always waited on the network. Manga opened from Browse never showed their description, author or genres. A previous manga's late results could overwrite the page. |
| `2e3f62d`, `cc492c4`, `7d10396` | Flatpak build | The manifest targeted an end-of-life runtime, launched with a script that cannot work in the sandbox, and copied the code so `import mihon` failed. Dependencies were never pinned. |
| `eaff2ea` | Bridge test | CI failed on a race: the bridge wrote its challenge request in place, and the reader of that file could see it half-written. Run 20 times under full CPU load with no failure. |
| `a79c598` | Reader fixes | Webtoon progress was never saved and chapters always reopened at the top. All webtoon strips loaded at once and were padded to 800 px. Zoom did nothing. Taps blocked the mouse wheel. Next chapter skipped unnumbered chapters. |

## Architecture

```text
mihon/
├── core/            database, models, HTTP, caching, downloads, updates,
│   │                backup import/export, search, fetch policy, reader rules
│   └── tracking/    AniList, MyAnimeList, credentials, retry queue
├── extensions/      built-in sources, local source, APK extractor,
│                    JVM bridge client, repository manager
└── ui/              GTK views and presenters
bridge/              Kotlin JSON-RPC server that runs APK extensions
data/                desktop entry, metainfo, icons, Flatpak manifest
docs/                specs, parity workflow, this document
tests/               pytest suite
```

- **Storage:** one SQLite database with WAL mode, foreign keys and a single write lock. Schema changes run as guarded migrations at startup, so old databases upgrade in place.
- **Threads:** network and disk work run on worker threads, and every UI update returns to the GTK main loop through `GLib.idle_add`.
- **Testable rules:** decision logic is kept out of GTK code so it can be tested without a display. Examples are `fetch_policy.py`, `reader_logic.py`, `page_cache.py`, `library_presenter.py` and `source_ids.py`.
- **Data location:** `~/.local/share/mihon-linux/` for a source checkout, and `~/.var/app/io.github.nabhya8013.MihonLinux/` for the Flatpak.

## Known limitations

- **No JVM extensions in the Flatpak:** the sandbox has no JDK, so APK extensions only work in a source checkout.
- **Chapter order on built-in sources:** MangaDex and AllManga do not record the source's chapter order. For them, next and previous chapter fall back to chapter numbers, and unnumbered chapters cannot be placed.
- **Backup coverage:**
  - Tracker links in a backup are not restored.
  - History restores only the last-read time per chapter.
  - The `.tachibk` format has no version field to validate against.
- **Caching:** the cache ages are fixed (24 hours and 1 hour), with no setting. There is no ETag or `If-Modified-Since` support.
- **Reader checks:** taps, keys and the scroll wheel were checked by calling their handlers in a real window, not with real mouse or keyboard input.
- **No screenshots:** the README does not have any yet.

## What is left

Roughly in order of value:

1. **Bridge gaps**, fixed when a real extension needs them: per-image headers from `fetchImage()`, sources that load pages one by one, `android.text.format.DateFormat`, and a coroutines bridge for newer extensions.
2. **Smaller features:** an Upcoming view, an adaptive layout for narrow windows, a scheduled tracker pull, Security and Privacy settings, and README screenshots.
3. **Housekeeping:** move the workflows to `actions/checkout@v5` before Node 20 support ends, and check CI when `ubuntu-latest` moves to Ubuntu 26 on 19 October 2026.
4. **Lower value:** image filters (colour profiles, background matching, OLED black trimming) and animated page transitions.
