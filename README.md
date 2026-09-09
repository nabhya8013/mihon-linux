# Mihon Linux

Native GTK4/Libadwaita manga reader for Linux, inspired by
[Mihon](https://github.com/mihonapp/mihon)/Tachiyomi.

> **Status:** early, actively developed. Three built-in sources plus a JVM bridge for
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
- **Updates** tab: scans the library, fetches latest chapters per source, stores new
  chapters, recalculates unread counts, and shows per-manga results
- **History** tab: recently read chapters
- **Reader**: paged (single/double page, RTL/LTR) and webtoon/continuous modes, with
  chapter progress and download support
- **APK extension bridge**: loads Tachiyomi/Mihon `.apk` extensions through a Kotlin
  JVM process (see [`bridge/README.md`](bridge/README.md))
- **`.tachibk` import**: restore an Android Mihon backup (library, categories, chapter
  metadata) from *More → Data*
- **Anti-bot layer**: browser-grade TLS via `curl_cffi`, a WebKit challenge-solver
  window for Cloudflare/DDoS-Guard, and a persistent cookie jar shared between the
  Python app and the JVM bridge
- Cross-source **migration search**

## Project Structure

```text
mihon/
├── core/         # database, models, HTTP client, downloader, updater, cookie store,
│                 # challenge bridge, .tachibk importer
├── extensions/   # built-in sources + APK extractor + JVM extension bridge
└── ui/           # GTK views (library, browse, updates, history, reader, more,
                  # manga detail, challenge solver)

bridge/           # standalone Kotlin JSON-RPC bridge for APK/JVM extensions
```

Application data lives under `~/.local/share/mihon-linux/` (SQLite DB, covers,
downloads, `cookies.json`).

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

## Troubleshooting

| Symptom | Fix |
|---|---|
| `error: externally-managed-environment` on `pip install` | Use a venv (see *Python dependencies*). |
| `Bridge JAR not found at .../mihon-bridge-1.0-SNAPSHOT.jar` | Build it: `cd bridge && ./gradlew jar`. |
| Challenge-solver window never appears on a Cloudflare block | Install WebKitGTK 6.0 (`webkitgtk6.0` / `gir1.2-webkit-6.0`). |
| `Failed to initialize GTK window` / app exits immediately | Run inside a graphical session — `DISPLAY` or `WAYLAND_DISPLAY` must be set. |
| `./gradlew jar` fails with a JRE / "no compiler" error | Install a full JDK 21, not just the JRE, and point `JAVA_HOME` at it. |

## Notes

- Network connectivity is required for source fetch/update operations.
- JVM extensions require the bridge JAR and Java 21.

## License

This project is inspired by and aims for behavioral parity with Mihon/Tachiyomi
(Apache 2.0). A `LICENSE` file for this repository is pending.
