# Mihon Linux

Native GTK4/Libadwaita manga reader for Linux, inspired by
[Mihon](https://github.com/mihonapp/mihon)/Tachiyomi.

> **Status:** early, actively developed. Four built-in sources (three online, one local) plus a JVM bridge for
> Tachiyomi-style APK extensions. See [`docs/parity-workflow.md`](docs/parity-workflow.md)
> for the roadmap toward Android feature parity.

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
- **Reader**: paged (single/double/auto page, RTL/LTR) and webtoon/continuous modes,
  with chapter progress and download support. Pages are prefetched in a sliding
  window so a page turn is instant, landscape scans are detected and shown as
  full two-page spreads, and webtoon strips stitch together with no seam
- **APK extension bridge**: loads Tachiyomi/Mihon `.apk` extensions through a Kotlin
  JVM process (see [`bridge/README.md`](bridge/README.md))
- **Source filters**: sources that expose a Tachiyomi `FilterList` (genre groups,
  status selects, tri-state tags, sort order, free-text fields) get a native GTK
  filter sheet in the source catalog, and the edited state is sent back to the
  source on search
- **`.tachibk` import/export**: *More → Backup and Restore* writes a backup Android
  Mihon can read and restores one with a preview first (manga, chapters, how many
  already exist). Restore brings back chapters, read progress, categories and history,
  with a **Merge** (keep local data, add what is missing; read never becomes unread) or
  **Overwrite** choice and a progress bar. Restoring never removes manga or chapters.
  Source IDs use upstream's hash, so backups move in both directions
- **Anti-bot layer**: browser-grade TLS via `curl_cffi`, a WebKit challenge-solver
  window for Cloudflare/DDoS-Guard, and a persistent cookie jar shared between the
  Python app and the JVM bridge
- **Keyboard shortcuts**: `Ctrl+K` or `/` global search, `Ctrl+R` / `F5` refresh,
  `Ctrl+1`–`Ctrl+5` tabs, `Ctrl+?` for the full list
- **Drag and drop**: drop an APK onto the Extensions tab to install it, drag category
  rows to reorder them
- **Tracking**: two-way sync with AniList and MyAnimeList. Reading past 85% of a
  chapter updates the remote entry, failed updates are queued and retried, and
  status/progress/score can be edited from the manga page. Tokens live in the system
  keyring
- **Global search** (`Ctrl+K`): queries every installed source in parallel and fills
  in a section per source as each one answers, with a per-source timeout so one slow
  source cannot hold up the rest. Doubles as the cross-source migration search

## Project Structure

```text
mihon/
├── core/         # database, models, HTTP client, downloader, updater, cookie store,
│                 # challenge bridge, .tachibk importer/exporter, source ids,
│                 # page cache, disk cache, global search
│   └── tracking/ # AniList + MyAnimeList, credential store, retry queue
├── extensions/   # built-in sources + APK extractor + JVM extension bridge
└── ui/           # GTK views (library, browse, updates, history, reader, more,
                  # manga detail, challenge solver, source filters), plus the
                  # library presenter and toast notifications

data/             # .desktop entry, AppStream metainfo, app icons, Flatpak manifest
.github/          # CI and release workflows

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
The automated pytest suite is under `tests/` (`python -m pytest tests/`).

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

`data/io.github.nabhya8013.MihonLinux.yml` is a Flatpak manifest. It is **not
buildable as committed**: a Flatpak build has no network access, so the Python
dependencies must first be turned into hash-pinned sources with
`flatpak-pip-generator`. The manifest header has the exact command. It is left
incomplete rather than stubbed, so a build fails loudly instead of appearing to work.

CI runs on every push: tests under `xvfb`, an import check of every module, `ruff`
error-level lint, `desktop-file-validate`, `appstreamcli validate`, and a Gradle
build of the bridge JAR. Tagging `v*` builds a release with a generated changelog.

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
