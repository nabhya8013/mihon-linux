# Mihon Linux UI Parity Workflow

This document defines the implementation workflow for closing UI gaps with Mihon Android.

Related docs:
- Per-feature strategic roadmap and priority order: `port_parity_roadmap.md` (repo root, local-only).
- Library controls behavior contract: [`specs/library-controls.md`](specs/library-controls.md).

## Progress

| Epic | Status |
|---|---|
| 1) Browse Parity | **Done** — Sources, Extensions (repo browse/install/update), and Migrate tabs; concurrent global search with `src:`/`id:` queries |
| 2) Advanced Library Controls | **Done** — `4ad2f20` |
| 3) Category Management UI | **Done** — `e3451e3` |
| 4) Manga Detail Parity | **Done** — detail, chapter list with sort modes, checkbox multi-select batch actions, AniList/MAL tracking with two-way sync |
| 5) Reader Advanced Settings | Partial — paged, double-page, and webtoon modes; persisted direction/layout/scale/crop-borders/background/keep-screen-on; working zoom and fit-width; webtoon progress, resume and lazy loading; tap-zone layouts (Standard, Kindle, Edges, Off); scroll-wheel page turns; per-page loading spinner; end-of-chapter card; webtoon side padding; chapter navigation in source order; full keyboard control |
| 6) Smart Updates and Upcoming | Partial — scheduled background updates, per-category exclusion, skip-dropped, desktop notifications shipped; Upcoming view pending |
| 7) Download Manager Parity | **Done** — queue UI with cancel/retry/remove, reorder and move-to-front priority, download location and worker count settings |
| 8) Full Settings Parity | Partial — dedicated Settings pages (Reader, Appearance, Library, Downloads and Data, Backup and Restore, Sources, Tracking, About), `.tachibk` import/export with preview and merge/overwrite shipped; Security/Privacy pending |

Sprint 0 (anti-bot), `.tachibk` import/export, tracking, and local source are tracked separately in
`PORT_PARITY_IMPLEMENTATION_LOG.md` (repo root, local-only) — all shipped.

## Core Delivery Pattern (Use For Every Epic)

1. Define scope: finalize screens, interactions, and non-goals for the epic.
2. Define data contract: DB schema/settings keys/state models needed.
3. Implement backend/service layer first.
4. Add UI skeleton and navigation entry points.
5. Wire state and async flows (loading, empty, error, retry).
6. Persist settings/state and verify restore on restart.
7. Add tests (unit/integration where practical) plus manual QA checklist.
8. Validate, then merge to `main`.

## Epic Workflows

## 1) Browse Parity

Goal: Add Android-like `Sources / Extensions / Migrate` parity and global search behaviors.

1. Write UX spec for Migrate and global search (`src:`, `id:` query handling).
2. Add migration + global search service layer.
3. Extend browse navigation with `Migrate` surface.
4. Implement result ranking, dedupe, and conflict UI.
5. Add fallback/empty/error states for source/network failures.
6. Validate full migration flow end-to-end.

Done when:
- User can migrate manga source from UI.
- Global search supports source-scoped queries consistently.

## 2) Advanced Library Controls

Goal: Match Android-level library filtering, sorting, display modes, and batch operations.

1. Freeze filter/sort/display matrix and defaults.
2. Add persisted library preferences in DB settings.
3. Implement filter/sort state engine separate from widgets.
4. Add UI controls (sort, display mode, advanced filters, batch actions).
5. Add per-category preference handling.
6. Validate behavior persistence and edge cases (large libraries).

Done when:
- Library behavior is configurable and persistent across sessions.

## 3) Category Management UI

Goal: Add full category lifecycle from UI.

1. Add UX spec for create/edit/delete/reorder.
2. Extend DB API for stable reorder operations.
3. Implement category manager dialog/screen.
4. Add drag-and-drop reorder support.
5. Add manga assignment/unassignment UX.
6. Test integrity: no orphan mappings, correct sort order after restart.

Done when:
- Category management is complete without CLI/manual DB edits.

## 4) Manga Detail Parity

Goal: Expand manga detail to include tracking/migration/chapter management parity.

1. Spec tracking cards, chapter filter model, and batch actions.
2. Add tracking abstraction and account/token storage integration.
3. Add chapter filters (read/unread/downloaded/bookmarked where applicable).
4. Add batch actions (mark/read/unread/download/delete local).
5. Add migration entry point from detail screen.
6. Validate chapter operations at scale and conflict handling.

Done when:
- Manga detail supports advanced chapter and tracking workflows.

## 5) Reader Advanced Settings

Goal: Bring reader settings close to Android depth.

1. Define supported reader settings and defaults.
2. Persist settings keys and migration for existing installs.
3. Expand reader settings UI (layout, scaling, crop, orientation, tap zones).
4. Apply settings live and on chapter load.
5. Add regression checks for paged and webtoon modes.
6. Validate keyboard/mouse/touch interactions across modes.

Done when:
- Reader settings are deep, persistent, and reliably applied.

## 6) Smart Updates and Upcoming

Goal: Add automated/scheduled update surfaces and upcoming visibility.

1. Define smart update rules and scheduling policy.
2. Implement scheduler state and job orchestration.
3. Add Updates UI filters/modes for smart and upcoming views.
4. Add retry/error surfacing per source/manga.
5. Add settings controls for update windows and constraints.
6. Validate with mixed source reliability and large libraries.

Done when:
- Users can rely on smart updates without manual-only checks.

## 7) Download Manager Parity

Goal: Add rich queue management controls.

1. Define queue model operations (pause/resume/reorder/retry/remove).
2. Extend downloader core API for queue control and state transitions.
3. Build queue-centric UI (active, queued, failed, completed sections).
4. Add per-item and global controls.
5. Add persistence for queue recovery after app restart.
6. Validate concurrency, retries, and cancel safety.

Done when:
- Download queue is actively manageable and fault-tolerant.

## 8) Full Settings Parity

Goal: Expand `More/Settings` into Android-like settings coverage.

1. Define settings information architecture:
   - Reader
   - Library
   - Browse/Sources
   - Downloads/Data
   - Tracking
   - Backup/Restore
   - Security/Privacy
   - Appearance
2. Add missing settings keys/schema and defaults.
3. Implement dedicated settings screens (not single compact panel).
4. Implement backup/restore with schema versioning and validation.
5. Add import/export error handling and recovery UX.
6. Add QA matrix for upgrade paths and partial backup restores.

Done when:
- Settings are comprehensive, structured, and safely recoverable.

## Execution Order

The authoritative priority order lives in `port_parity_roadmap.md`
("Revised Priority Order" / "Recommended sprint plan"), which sequences these UI
epics alongside the anti-bot, backup, and tracking work. Follow that order rather
than a separate list here.
