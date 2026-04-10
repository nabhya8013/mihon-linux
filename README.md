# Mihon Linux

Native GTK4/Libadwaita manga reader for Linux, inspired by Mihon/Tachiyomi.

## Features

- Native GTK4 UI (no Electron)
- Library management with categories, history, and unread tracking
- Browse tab with built-in sources:
  - MangaDex
  - AllManga
- Reader with chapter progress + download support
- APK extension bridge (Tachiyomi-style extensions via JVM)
- Updates tab:
  - scans all manga in your library
  - fetches latest chapters from each source
  - stores new chapters in the DB
  - updates unread counts
  - shows per-manga update results

## Project Structure

```text
mihon/
├── core/         # database, models, downloader, updater
├── extensions/   # built-in + JVM extension bridge
└── ui/           # GTK views (library, browse, updates, reader, etc.)

bridge/           # Kotlin JSON-RPC bridge used for APK/JVM extensions
```

## Requirements

### System packages

Install GTK4, Libadwaita, GI bindings, and Java 21.

### Fedora

```bash
sudo dnf install -y python3 python3-pip python3-gobject python3-requests gtk4 libadwaita java-21-openjdk
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-gi python3-requests gir1.2-gtk-4.0 gir1.2-adw-1 openjdk-21-jdk
```

### Python dependencies

```bash
pip install -r requirements.txt
```

## Build and Run

### 1. Build bridge JAR (Java 21)

Use this exact command:

```bash
cd /home/your-name/mihon-linux/bridge && JAVA_HOME=/usr/lib/jvm/java-21-openjdk ./gradlew jar
```

### 2. Run app

```bash
cd /home/your-name/mihon-linux && python3 run.py
```

## Updates Page Workflow

1. Add manga to library (from Browse -> manga detail -> Add to Library).
2. Open `Updates` tab.
3. Click `Check Updates`.
4. App checks each library manga source and inserts newly discovered chapters.
5. Unread counts are recalculated and shown in library cards + update rows.

## Quick Update-Check Smoke Test (CLI)

You can run a non-UI check directly:

```bash
cd /home/your-name/mihon-linux
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

## Notes

- Network connectivity is required for source fetch/update operations.
- GTK app must run inside a graphical session (`DISPLAY` or `WAYLAND_DISPLAY` set).
- JVM extensions require the bridge JAR and Java 21.
