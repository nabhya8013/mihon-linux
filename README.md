# Mihon Linux

Native GTK4/Libadwaita manga reader for Linux, inspired by
[Mihon](https://github.com/mihonapp/mihon)/Tachiyomi.

> **Status:** early, actively developed. Four built-in sources (three online, one local)
> plus a JVM bridge for Tachiyomi-style APK extensions, and a Flatpak build. See
> [`docs/project-status.md`](docs/project-status.md) for everything built so far and what
> is left, and [`docs/parity-workflow.md`](docs/parity-workflow.md) for the roadmap toward
> Android feature parity.

## Screenshots

<!-- Add screenshots here: drop PNGs in docs/screenshots/ and reference them, e.g.
![Library](docs/screenshots/library.png) -->

_Not yet added._

## Features

- Native GTK4 UI (no Electron)
- **Library** with categories, per-category preferences (sort, filter, grid/list
  display), batch actions, and unread tracking
- **Browse** with built-in sources:
  - MangaDex
  - AllManga (allmanga.to / allanime.day)
  - MangaFire
  - **Local** — your own CBZ/ZIP/CBR/RAR archives and image folders
- **Updates** tab: scans the library, fetches latest chapters per source, stores new
  chapters, recalculates unread counts, and shows per-manga results
- **History** tab: recently read chapters
- **Manga page**: details, chapter list with number / source-order / upload sorting,
  filters, search and checkbox batch actions. Saved chapters show instantly; the
  source is only asked again when the copy is stale (details after 24 hours,
  chapters after 1 hour), and a **Refresh** button fetches on demand
- **Reader**: paged (single/double/auto page, RTL/LTR) and webtoon/continuous modes.
  - Fit page or fit width (full width, scrolls), and zoom from 30% to 300%
  - Pages prefetched in a sliding window, so a page turn is instant
  - Landscape scans shown as full two-page spreads
  - Webtoon strips sized from their own aspect ratio and joined with no seam, loaded
    only near the one you are reading, with progress saved as you scroll and the
    chapter reopening where you left off
  - Previous/next chapter in the source's own order, so unnumbered chapters are not
    skipped
  - Tap zones: Standard (left/right thirds), Kindle (menu along the top), Edges
    (narrow side strips) or Off, without blocking the mouse wheel. Optionally the
    scroll wheel turns pages once a page is scrolled to its end
  - A loading spinner appears only when a page is not cached yet
  - An end-of-chapter card ("Finished Chapter 2 · Next: Chapter 3") instead of jumping
    straight into the next chapter
  - Webtoon side padding, so strips do not stretch across a wide window
- **Downloads**: queue with cancel, retry, remove, reorder and move-to-front, a
  configurable folder and number of parallel downloads; downloaded chapters read
  from disk in both reader modes
- **Smart updates**: library checks on startup and every 6, 12 or 24 hours, skipping
  dropped series and excluded categories, with desktop notifications
- **APK extension bridge**: loads Tachiyomi/Mihon `.apk` extensions through a Kotlin
  JVM process (see [`bridge/README.md`](bridge/README.md))
- **Source filters**: sources that expose a Tachiyomi `FilterList` (genre groups,
  status selects, tri-state tags, sort order, free-text fields) get a native GTK
  filter sheet in the source catalog, and the edited state is sent back to the
  source on search
- **Backup and Restore** (`.tachibk`): *More → Backup and Restore* writes a backup
  Android Mihon can read and restores one with a preview first (manga, chapters, how
  many already exist). Restore brings back chapters, read progress, categories and
  history, with a **Merge** (keep local data, add what is missing; read never becomes
  unread) or **Overwrite** choice and a progress bar. Restoring never removes manga or
  chapters. Source IDs use upstream's hash, so backups move in both directions
- **Anti-bot layer**: browser-grade TLS via `curl_cffi`, a WebKit challenge-solver
  window for Cloudflare/DDoS-Guard, and a persistent cookie jar shared between the
  Python app and the JVM bridge
- **Keyboard shortcuts**: `Ctrl+K` or `/` global search, `Ctrl+R` / `F5` refresh,
  `Ctrl+1`–`Ctrl+5` tabs, `Ctrl+W` back, `Ctrl+?` for the full list. In the reader:
  arrow keys or `A`/`D` turn pages (following the reading direction), `W`/`S`/`Space`
  and `Page Up`/`Page Down` scroll or page, `Backspace` goes back, `Home`/`End` jump to
  the first or last page, `N`/`P` next and previous chapter, `+`/`-`/`0` zoom, `F` or
  `F11` fullscreen, `Esc` closes
- **Drag and drop**: drop an APK onto the Extensions tab to install it, drag category
  rows to reorder them
- **Tracking**: two-way sync with AniList and MyAnimeList. Reading past 85% of a
  chapter updates the remote entry, failed updates are queued and retried, and
  status/progress/score can be edited from the manga page. Tokens live in the system
  keyring
- **Global search** (`Ctrl+K`): queries every installed source in parallel and fills
  in a section per source as each one answers, with a per-source timeout so one slow
  source cannot hold up the rest. Doubles as the cross-source migration search
- **Settings** split into pages: Reader, Appearance (System/Light/Dark), Library,
  Downloads and Data, Backup and Restore, Sources, Tracking, About
- **Flatpak**: builds on the GNOME 50 runtime with every Python dependency pinned by
  hash (see *Packaging*)

## Project Structure

```text
mihon/
├── core/         # database, models, HTTP client, downloader, updater, cookie store,
│                 # challenge bridge, .tachibk importer/exporter, source ids,
│                 # page cache, disk cache, global search, fetch policy (when to
│                 # refetch), reader logic (page sizing, taps, chapter order)
│   └── tracking/ # AniList + MyAnimeList, credential store, retry queue
├── extensions/   # built-in sources + APK extractor + JVM extension bridge
└── ui/           # GTK views (library, browse, updates, history, reader, more,
                  # manga detail, challenge solver, source filters), plus the
                  # library presenter and toast notifications

data/             # .desktop entry, AppStream metainfo, app icons, Flatpak manifest,
                  # hash-pinned Python dependencies for the Flatpak
docs/             # project status, parity workflow, behaviour specs
tests/            # pytest suite
.github/          # CI, Flatpak and release workflows

bridge/           # standalone Kotlin JSON-RPC bridge for APK/JVM extensions
```

Application data lives under `~/.local/share/mihon-linux/` (SQLite DB, covers,
`page-cache/`, downloads, `logs/`, `cookies.json`). Covers are kept; cached chapter
pages are pruned once they pass 512 MB, and can be cleared from *More → Downloads and Data*.

## Requirements

- Python 3.10+
- GTK 4, Libadwaita, PyGObject (GI) bindings
- WebKitGTK 6.0 (optional — enables the challenge-solver window)
- Java 21 (only for APK/JVM extensions)

### Fedora

```bash
sudo dnf install -y python3 python3-pip python3-gobject python3-requests \
  gtk4 libadwaita webkitgtk6.0 java-21-openjdk
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv python3-gi python3-requests \
  gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 openjdk-21-jdk
```

### Python dependencies

Modern Fedora/Ubuntu block `pip install` into the system Python (PEP 668), so use a
virtual environment. PyGObject is provided by the system packages above, so let the
venv see them:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt`:

| Package | Purpose |
|---|---|
| `curl_cffi` | default HTTP backend — real Chrome TLS fingerprint (`requests` is only a fallback) |
| `requests` | fallback HTTP backend when `curl_cffi` is unavailable |
| `PyGObject` | GTK/GI bindings (usually already satisfied by the system package) |
| `androguard` | reads `AndroidManifest.xml` when converting an extension `.apk` |
| `protobuf` | reads and writes `.tachibk` backups (the schema is built at runtime, no `protoc` needed) |
| `rarfile` | optional: `.cbr`/`.rar` chapters in the local source, with an unrar tool on `PATH` |

APK → JAR conversion also downloads [`dex2jar`](https://github.com/pxb1988/dex2jar)
on first use into `~/.local/share/mihon-linux/tools/`.

## Build and Run

### 1. Build the bridge JAR (only needed for APK/JVM extensions)

```bash
cd bridge
JAVA_HOME=$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")") ./gradlew jar
```

If `javac` is not on `PATH`, set `JAVA_HOME` explicitly:

- Fedora: `/usr/lib/jvm/java-21-openjdk`
- Debian/Ubuntu: `/usr/lib/jvm/java-21-openjdk-amd64`

The JAR is written to `bridge/build/libs/mihon-bridge-1.0-SNAPSHOT.jar`, which is
where the app looks for it.

### 2. Run the app

```bash
python3 run.py
```

## Updates Page Workflow

1. Add manga to the library (Browse → manga detail → *Add to Library*).
2. Open the **Updates** tab.
3. Click **Check Updates**.
4. The app checks each library manga's source and inserts newly discovered chapters.
5. Unread counts are recalculated and shown on library cards and update rows.

To check automatically, turn on scheduled updates in *More → Library* and pick an
interval (every 6, 12 or 24 hours). Categories can be excluded there, and dropped
series skipped. A manga opened right after an update does not fetch its chapter list
again.

## Quick Update-Check Smoke Test (CLI)

A non-UI check:

```bash
python3 - <<'PY'
from mihon.core.library_updater import LibraryUpdater
s = LibraryUpdater().check_updates()
print({
    "checked_manga": s.checked_manga,
    "updated_manga": s.updated_manga,
    "new_chapters": s.new_chapters,
    "failures": s.failures,
})
if s.errors:
    print("first_error:", s.errors[0])
PY
```

Other manual source probes live in the repo root as `test_mangadex.py`,
`test_allmanga.py`, and `test_chapters.py` (run with `python3 test_mangadex.py`).
The automated pytest suite is under `tests/` (`python -m pytest tests/`, about 470
tests). The bridge has its own tests: `cd bridge && ./gradlew test`.

## Local Source

Point *More → Sources → Local source* at a folder laid out one directory per series:

```text
~/Manga/
  Berserk/
    cover.jpg           # optional; the first page is used otherwise
    details.json        # optional metadata override
    Chapter 1.cbz
    Chapter 2.cbz
  Akira/
    Volume 01/          # a folder of loose images works too
      001.jpg
      002.jpg
```

CBZ and ZIP are the same container and both work. CBR/RAR also works, given the
optional `rarfile` package (in `requirements.txt`) plus an unrar-compatible tool
on `PATH` — `unrar`, `unar`, or `bsdtar`, since the RAR format itself is
proprietary and not implementable in Python alone. Without either, `.cbr`/`.rar`
chapters still appear but yield no pages; check the log for which one is
missing. `details.json` accepts `title`, `author`, `artist`, `description`,
`status` and `genre`.

Chapter numbers are parsed from filenames. When a name has no number, the source's
own file ordering is used instead — switch the chapter list to **Source order** from
the sort menu on the manga page.

## Tracking Setup

AniList and MyAnimeList both require an API client. A desktop app cannot ship a
shared secret — anything in the source is public — so you register your own, which
takes about a minute:

| Service | Where | What to enter |
|---|---|---|
| AniList | <https://anilist.co/settings/developer> | Redirect URL `https://anilist.co/api/v2/oauth/pin` |
| MyAnimeList | <https://myanimelist.net/apiconfig> | App type "other", redirect URL anything you like |

Paste the client ID into *More → Tracking*, press **Log in**, approve in the browser,
then paste back the code it shows you. Neither flow needs a client secret: AniList
uses the implicit grant and MyAnimeList uses PKCE.

Tokens are stored in your login keyring through libsecret. If no keyring is
available, the app falls back to its own database and says so in Settings — the
tokens are not encrypted in that case.

## Desktop Integration

Install the launcher entry, icon, and AppStream metadata so the app appears in your
application menu and software centre:

```bash
scripts/install-desktop-files.sh              # per-user, into ~/.local
scripts/install-desktop-files.sh /usr         # system-wide (needs root)
scripts/install-desktop-files.sh --uninstall  # remove
```

This drops a `mihon-linux` launcher on `PATH` pointing back at this checkout, so make
sure `~/.local/bin` is on your `PATH`.

## Packaging

`data/io.github.nabhya8013.MihonLinux.yml` is a Flatpak manifest for the GNOME 50
runtime. Python dependencies are pinned by hash in `data/python3-requirements.json`
because a Flatpak build has no network access. Build and install it locally:

```bash
flatpak install -y flathub org.gnome.Platform//50 org.gnome.Sdk//50 org.flatpak.Builder
flatpak run org.flatpak.Builder --user --install --force-clean build-dir \
    data/io.github.nabhya8013.MihonLinux.yml
flatpak run io.github.nabhya8013.MihonLinux
```

The sandbox does not include a JDK, so APK/JVM extensions are unavailable in the
Flatpak build; the built-in sources and the local source work. After changing
`requirements.txt`, regenerate the pinned module with the command in the manifest
header; a test fails if the two disagree. Its data lives under
`~/.var/app/io.github.nabhya8013.MihonLinux/`, separate from a source checkout.

CI runs on every push: tests under `xvfb`, an import check of every module, `ruff`
error-level lint, `desktop-file-validate`, `appstreamcli validate`, and a Gradle
build of the bridge JAR. A separate workflow builds the Flatpak when packaging or
app code changes and uploads the bundle as an artifact. Tagging `v*` builds a release with a generated changelog.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `error: externally-managed-environment` on `pip install` | Use a venv (see *Python dependencies*). |
| `Bridge JAR not found at .../mihon-bridge-1.0-SNAPSHOT.jar` | Build it: `cd bridge && ./gradlew jar`. |
| Challenge-solver window never appears on a Cloudflare block | Install WebKitGTK 6.0 (`webkitgtk6.0` / `gir1.2-webkit-6.0`). |
| `Failed to initialize GTK window` / app exits immediately | Run inside a graphical session — `DISPLAY` or `WAYLAND_DISPLAY` must be set. |
| `./gradlew jar` fails with a JRE / "no compiler" error | Install a full JDK 21, not just the JRE, and point `JAVA_HOME` at it. |
| App does not appear in the application menu | Run `scripts/install-desktop-files.sh`, then log out and back in. |
| Disk usage growing under `~/.local/share/mihon-linux` | Clear the page cache from *More → Downloads and Data*. Downloads and covers are kept. |
| Tracking says "Client ID needed" | Register an API client and paste its ID in *More → Tracking* (see *Tracking Setup*). |
| Tracker updates stuck in "waiting" | Check you are still logged in, then press **Retry now** in *More → Tracking*. |
| Local series not showing up | Check the folder in *More → Sources → Local source*, then press **Rescan**. Each series needs its own subfolder. |
| A manga page shows old chapters | Press **Refresh** on the manga page. Chapter lists are reused for up to an hour. |
| Restoring a backup says the file is not readable | Make sure it is a `.tachibk` from Mihon or this app; other Tachiyomi forks' formats may differ. |
| A `.cbr`/`.rar` chapter has no pages | Install the `rarfile` package and an unrar-compatible tool (`unrar`, `unar`, or `bsdtar`), then check the log for which one is still missing. |

## Notes

- Network connectivity is required for source fetch/update operations.
- Logs are written to `~/.local/share/mihon-linux/logs/mihon.log`. Raise the level
  with `MIHON_LOG_LEVEL=DEBUG`.
- JVM extensions require the bridge JAR and Java 21.

## License

Released under the [MIT License](LICENSE).

This project is an independent reimplementation of, and aims for behavioral parity
with, [Mihon](https://github.com/mihonapp/mihon) (Apache 2.0). See [`NOTICE`](NOTICE)
for what is derived from upstream and how it is attributed. This project is not
affiliated with or endorsed by the Mihon or Tachiyomi projects.
