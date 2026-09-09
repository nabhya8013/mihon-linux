# Contributing

## Dev setup

```bash
git clone <repo> && cd mihon-linux
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
```

System packages (GTK 4, Libadwaita, PyGObject, optional WebKitGTK 6.0, JDK 21 for
extensions) are listed in the [README](README.md#requirements).

Build the extension bridge (only if you touch `bridge/` or test APK extensions):

```bash
cd bridge && ./gradlew jar    # set JAVA_HOME if javac isn't on PATH
```

Run the app: `python3 run.py`.

## Code layout

| Path | What |
|---|---|
| `mihon/core/` | DB, models, HTTP client, downloader, library updater, cookie store, challenge bridge, `.tachibk` importer |
| `mihon/extensions/` | built-in sources (`mangadex`, `allmanga`, `mangafire`), APK extractor, JVM bridge + proxies |
| `mihon/ui/` | GTK views — `main_window` (tab shell), `library`, `browse`, `updates`, `reader`, `manga_detail`, `challenge_solver`, `library_state` (filter/sort engine) |
| `bridge/` | standalone Kotlin JSON-RPC bridge — see [`bridge/README.md`](bridge/README.md) |
| `docs/` | specs and the parity workflow |

## Tests

Automated (pytest):

```bash
python -m pytest tests/
```

Covers `http_client`, `challenge_bridge`, `tachibk_importer`.

Manual source probes (hit the live network, not pytest) live in the repo root:
`test_mangadex.py`, `test_allmanga.py`, `test_chapters.py`, `test_dialog.py` — run
directly with `python3 test_mangadex.py`.

Bridge JUnit: `cd bridge && ./gradlew test`. Full slice check:
`scripts/verify_slice5.sh`.

## Knowledge graph

The repo carries a `graphify` knowledge graph under `graphify-out/` (gitignored).
Per `.agent/rules/graphify.md`: after changing code,
run `graphify update .` to keep it current (AST-only, no API cost). Read
`graphify-out/GRAPH_REPORT.md` before large architecture changes.

## Commits & branches

- Branch off `main`; open a PR.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:` …).
- Keep `CHANGELOG.md` updated for user-visible changes.

## Roadmap

`docs/parity-workflow.md` tracks the UI parity epics and their status. The deeper
strategic roadmap (`port_parity_roadmap.md`) and implementation log
(`PORT_PARITY_IMPLEMENTATION_LOG.md`) are local-only (gitignored) working notes.
