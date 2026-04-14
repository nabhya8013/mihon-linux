# Mihon Linux UI Parity Workflow

This document defines the implementation workflow for closing UI gaps with Mihon Android.

## Core Delivery Pattern (Use For Every Epic)

1. Define scope: finalize screens, interactions, and non-goals for the epic.
2. Define data contract: DB schema/settings keys/state models needed.
3. Implement backend/service layer first.
4. Add UI skeleton and navigation entry points.
5. Wire state and async flows (loading, empty, error, retry).
6. Persist settings/state and verify restore on restart.
7. Add tests (unit/integration where practical) plus manual QA checklist.
8. Ship behind a feature flag; remove flag after validation pass.

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

## Execution Order (Recommended)

1. Advanced Library Controls
2. Category Management UI
3. Reader Advanced Settings
4. Download Manager Parity
5. Browse Parity
6. Manga Detail Parity
7. Smart Updates and Upcoming
8. Full Settings Parity

## Review Checklist

1. Are epic goals correct and complete?
2. Is execution order aligned with your priority?
3. Any epics to split further before implementation?
4. Any parity items you want explicitly out of scope for v1?
