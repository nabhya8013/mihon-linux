# Local Automation Test Run (2026-11-05)

## CI Status
- Latest run on `feature/next`: **success** (run 41985693703)
  - Python tests ✓, Lint ✓, Bridge JAR ✓, Desktop metadata ✓

## Local Python Tests
- `pytest tests/ -v`: **538 passed, 0 failed** (2.2s)
- Log: `test-logs/pytest-full.log`

## Bridge (Kotlin) Tests
- `./gradlew test`: **5 tests passed** (CloudflareInterceptorTest)
- Log: `test-logs/bridge-test.log`

## Lint & Metadata
- `ruff --select E9,F63,F7,F82 mihon/ tests/`: **All checks passed**
- `desktop-file-validate`: passed
- `appstreamcli validate`: passed (pedantic: 1)

## App Startup
- `python run.py` starts (GTK UI) — log: `test-logs/app-start.log`
- Observed: repo index loaded (1458 extensions), some cover image load warnings (404/format), Mesa warnings (environment). No crash in startup window tested.

## Source/Extension Smoke Tests
Tested 14 registered sources (4 built-in + 10 JVM-loaded EN). Results: `test-logs/source-test.json`, `test-logs/source-test.log`.

| Source | Search | Details | Chapters | Pages |
|---|---:|---:|---:|---:|
| MangaDex (builtin) | ✗ | - | - | - (JSON parse error in this run) |
| AllManga | ✓ (26) | ✓ | ✗ (0) | - |
| MangaFire | ✗ (403) | - | - | - |
| Local | ✗ (no content) | - | - | - |
| MangaDex (JVM) | ✓ (20) | ✓ | ✗ (0) | - |
| Mangakakalot | ✗ (403) | - | - | - |
| Weeb Central | ✓ (8) | ✓ | ✓ (701) | ✓ (51) |
| Asura Scans | ✗ | - | - | - |
| Flame Comics | ✗ | - | - | - |
| Mangahere | ✓ (12) | ✓ | ✓ (2) | ✗ (QuickJS API mismatch - fixed in bridge) |
| MangaK | ✓ (24) | ✓ | ✓ (748) | ✓ (18) |
| Toonily | ✗ | - | - | - |
| Manhua Plus | ✗ | - | - | - |
| MangaPill | ✓ (11) | ✓ | ✓ (701) | ✓ (51) |

**Working end-to-end (search→details→chapters→pages):** Weeb Central, MangaK, MangaPill. Mangahere improved after QuickJS fix (needs re-test).

## Batch Search/Match (Popular Manga)
- Pulled 200 popular manga titles from AniList: `test-logs/popular-200.json`
- Batch search run (resume-capable): `test-logs/batch-search.log`, console: `test-logs/batch-search-console.log`
- Progress at interruption: **95/200** processed. Run is still resumable; can continue to complete 200.
- Errors observed (logged): Cloudflare/403 on some sources, MangaDex 404 on some page fetches, Mangahere QuickJS `NoSuchMethodError` (bridge fixed; re-run recommended), occasional empty chapter lists.
- Summary artifacts: `test-logs/batch-search-summary.json` (partial, if generated).

## Issues Found & Fixed
1. **Bridge QuickJS API mismatch** (`app.cash.quickjs.QuickJs.evaluate(String)` missing): added `evaluate(script)` overload delegating to `evaluate(script, "?")`. Rebuilt bridge JAR. *File:* `bridge/src/main/kotlin/app/cash/quickjs/QuickJs.kt`
2. **CI failures** (protobuf/system package conflicts, GI import issues in mixed env): fixed workflow to use compatible Python/protobuf and system GI paths. CI now passing.

## Recommended Follow-ups
- Re-run batch search to completion (resume from log) after QuickJS fix.
- Investigate MangaDex builtin JSON parse error and JVM MangaDex returning 0 chapters for "Naruto" in this context.
- Add per-source page fetch headers/anti-bot handling for 403-prone sources (Mangakakalot, MangaFire, Asura).
- Consider marking Mangahere/QuickJS-dependent flows with integration test coverage.
