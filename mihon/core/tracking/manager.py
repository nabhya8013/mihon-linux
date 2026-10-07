"""
TrackManager: the app's single entry point to every tracking service.

The reader reports progress here, the manga detail view links and unlinks
entries here, and this is what decides whether an update goes out now or into
the retry queue.

Nothing in this module touches GTK. Callers that need to update a UI run
:meth:`sync_progress` on a worker thread and marshal the result themselves.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
import time
from typing import Callable, Dict, List, Optional

from .base import (
    STATUS_READING,
    TrackEntry,
    TrackerAuthError,
    TrackerError,
    TrackerService,
)
from .queue import TrackingQueue

logger = logging.getLogger("tracking.manager")

# Fraction of a chapter that counts as having read it. Android fires the sync
# near the end of the last page rather than on the page turn, so a chapter
# opened by accident does not register.
READ_THRESHOLD = 0.85

# How often a background pull refreshes remote state, in seconds.
DEFAULT_PULL_INTERVAL = 6 * 60 * 60


class TrackManager:
    """Owns the registered services, the local rows, and the retry queue."""

    def __init__(self, db, services: Optional[List[TrackerService]] = None):
        self._db = db
        self._services: Dict[str, TrackerService] = {}
        self.queue = TrackingQueue(db)
        self._lock = threading.Lock()

        for service in services or []:
            self.register(service)

    # ── Services ──────────────────────────────────────────────────────────

    def register(self, service: TrackerService):
        self._services[service.id] = service

    def get_service(self, provider: str) -> Optional[TrackerService]:
        return self._services.get(provider)

    @property
    def services(self) -> List[TrackerService]:
        return list(self._services.values())

    @property
    def logged_in_services(self) -> List[TrackerService]:
        return [s for s in self._services.values() if s.is_logged_in]

    # ── Local rows ────────────────────────────────────────────────────────

    def entries_for(self, manga_id: int) -> List[TrackEntry]:
        """Every tracker entry linked to a manga."""
        entries = []
        for row in self._db.get_manga_tracking(manga_id):
            entries.append(TrackEntry(
                provider=row.get("provider") or "",
                remote_id=str(row.get("remote_id") or ""),
                library_id=str(row.get("library_id") or ""),
                title=row.get("title") or "",
                status=row.get("status") or STATUS_READING,
                progress=float(row.get("progress") or 0),
                score=float(row.get("score") or 0),
                total_chapters=float(row.get("total_chapters") or 0),
                url=row.get("url") or "",
                started_at=row.get("started_at"),
                finished_at=row.get("finished_at"),
            ))
        return entries

    def entry_for(self, manga_id: int, provider: str) -> Optional[TrackEntry]:
        for entry in self.entries_for(manga_id):
            if entry.provider == provider:
                return entry
        return None

    def save_entry(self, manga_id: int, entry: TrackEntry):
        """Write an entry to the local database."""
        self._db.upsert_manga_tracking(
            manga_id=manga_id,
            provider=entry.provider,
            status=entry.status,
            progress=entry.progress,
            score=entry.score,
            url=entry.url,
            note="",
            remote_id=entry.remote_id,
            library_id=entry.library_id,
            title=entry.title,
            total_chapters=entry.total_chapters,
            started_at=entry.started_at,
            finished_at=entry.finished_at,
        )

    # ── Linking ───────────────────────────────────────────────────────────

    def link(self, manga_id: int, provider: str, remote_id: str) -> TrackEntry:
        """Bind a local manga to a remote entry and store the result."""
        service = self._require_service(provider)
        entry = service.bind(remote_id)
        entry.provider = provider
        self.save_entry(manga_id, entry)
        return entry

    def unlink(self, manga_id: int, provider: str, *, remote: bool = False):
        """
        Remove the local link, and optionally the remote list entry too.

        Deleting remotely is destructive and off by default: an accidental
        unlink must not wipe a user's AniList entry.
        """
        if remote:
            entry = self.entry_for(manga_id, provider)
            service = self._services.get(provider)
            unbind = getattr(service, "unbind", None)
            if entry is not None and callable(unbind):
                try:
                    unbind(entry)
                except TrackerError as exc:
                    logger.warning("remote unlink failed for %s: %s", provider, exc)

        self.queue.clear(manga_id=manga_id, provider=provider)
        self._db.remove_manga_tracking(manga_id, provider)

    def search(self, provider: str, query: str):
        return self._require_service(provider).search(query)

    # ── Progress ──────────────────────────────────────────────────────────

    @staticmethod
    def should_sync(page_index: int, page_count: int, threshold: float = READ_THRESHOLD) -> bool:
        """
        Whether a chapter is read far enough to count.

        ``page_index`` is zero-based. A one-page chapter counts as soon as
        that page is shown.
        """
        if page_count <= 0:
            return False
        if page_count == 1:
            return page_index >= 0
        return (page_index + 1) / page_count >= threshold

    def sync_progress(self, manga_id: int, chapter_number: float) -> List[TrackEntry]:
        """
        Push a chapter number to every service linked to this manga.

        Blocking; call it from a worker thread. A failed update is queued and
        the local row is still advanced, so the app's own view of progress
        does not depend on the network.
        """
        results = []
        for entry in self.entries_for(manga_id):
            updated = entry.with_progress(chapter_number)
            if updated.progress <= entry.progress and updated.status == entry.status:
                # Nothing new to report — an already-read chapter reopened.
                results.append(entry)
                continue

            self.save_entry(manga_id, updated)
            results.append(self._push(manga_id, updated))
        return results

    def set_entry(self, manga_id: int, entry: TrackEntry) -> TrackEntry:
        """Apply a user edit (status, score, progress) and push it."""
        self.save_entry(manga_id, entry)
        return self._push(manga_id, entry)

    def _push(self, manga_id: int, entry: TrackEntry) -> TrackEntry:
        service = self._services.get(entry.provider)
        if service is None or not service.is_logged_in:
            return entry

        try:
            remote = service.update(entry)
        except TrackerAuthError as exc:
            # Retrying cannot help until the user logs in again.
            logger.warning("%s needs re-authentication: %s", entry.provider, exc)
            return entry
        except TrackerError as exc:
            logger.info("queuing %s update for retry: %s", entry.provider, exc)
            self.queue.enqueue(manga_id, entry.provider, self._payload(entry))
            return entry

        remote.provider = entry.provider
        self.save_entry(manga_id, remote)
        return remote

    @staticmethod
    def _payload(entry: TrackEntry) -> dict:
        return {
            "remote_id": entry.remote_id,
            "library_id": entry.library_id,
            "title": entry.title,
            "status": entry.status,
            "progress": entry.progress,
            "score": entry.score,
            "total_chapters": entry.total_chapters,
            "url": entry.url,
        }

    # ── Retry queue ───────────────────────────────────────────────────────

    def process_queue(self, now: Optional[float] = None) -> int:
        """
        Deliver every queued update whose backoff has elapsed.

        Returns how many were delivered. Blocking; run it on a worker thread,
        at startup and after a sync succeeds.
        """
        delivered = 0
        for queued in self.queue.due(now):
            service = self._services.get(queued.provider)
            if service is None or not service.is_logged_in:
                continue

            entry = TrackEntry(provider=queued.provider, **{
                key: value for key, value in queued.payload.items()
                if key in TrackEntry.__dataclass_fields__ and key != "provider"
            })

            try:
                remote = service.update(entry)
            except TrackerAuthError as exc:
                logger.warning(
                    "dropping queued %s update, login required: %s", queued.provider, exc
                )
                self.queue.remove(queued.id)
                continue
            except TrackerError as exc:
                self.queue.mark_failed(queued.id, str(exc))
                continue

            remote.provider = queued.provider
            self.save_entry(queued.manga_id, remote)
            self.queue.remove(queued.id)
            delivered += 1

        return delivered

    # ── Pull sync ─────────────────────────────────────────────────────────

    def pull(self, manga_id: int) -> List[TrackEntry]:
        """
        Refresh one manga's entries from the remote services.

        This is the second direction: a score or status changed on the
        tracker's website makes its way back into the local database.
        """
        refreshed = []
        for entry in self.entries_for(manga_id):
            service = self._services.get(entry.provider)
            if service is None or not service.is_logged_in:
                refreshed.append(entry)
                continue
            try:
                remote = service.refresh(entry)
            except TrackerError as exc:
                logger.info("pull failed for %s: %s", entry.provider, exc)
                refreshed.append(entry)
                continue
            remote.provider = entry.provider
            self.save_entry(manga_id, remote)
            refreshed.append(remote)
        return refreshed

    def pull_all(self, manga_ids: List[int]) -> int:
        """Refresh many manga. Returns how many entries were updated."""
        updated = 0
        for manga_id in manga_ids:
            updated += len(self.pull(manga_id))
        return updated

    def pull_library(self) -> "PullSummary":
        """
        Pull every tracked library manga from the trackers you are logged in to.

        Run after a scheduled library update, so a score, status or progress
        changed on AniList or MyAnimeList shows up locally without opening
        each manga. Entries on a service you are not logged in to are left
        alone and not counted.
        """
        summary = PullSummary()
        if not self.logged_in_services:
            return summary
        logged_in = {s.id for s in self.logged_in_services}
        for manga_id in self._db.get_tracked_library_manga_ids():
            before = {
                e.provider: _sync_state(e)
                for e in self.entries_for(manga_id) if e.provider in logged_in
            }
            if not before:
                continue
            after = {e.provider: _sync_state(e) for e in self.pull(manga_id)}
            for provider, state in before.items():
                summary.checked += 1
                if after.get(provider) != state:
                    summary.changed += 1
        return summary

    # ── Internals ─────────────────────────────────────────────────────────

    def _require_service(self, provider: str) -> TrackerService:
        service = self._services.get(provider)
        if service is None:
            raise TrackerError(f"Unknown tracking service: {provider}")
        return service


def _sync_state(entry: TrackEntry):
    """The fields a pull can change and a user would notice."""
    return (entry.status, entry.progress, entry.score)


@dataclass
class PullSummary:
    checked: int = 0
    changed: int = 0


_manager: Optional[TrackManager] = None
_manager_lock = threading.Lock()


def get_track_manager(db=None) -> TrackManager:
    """The process-wide TrackManager, built with the bundled services."""
    global _manager
    with _manager_lock:
        if _manager is None:
            from ..database import get_db
            from .anilist import AniListTracker
            from .credentials import CredentialStore
            from .myanimelist import MyAnimeListTracker

            db = db or get_db()
            credentials = CredentialStore(db)
            _manager = TrackManager(db, services=[
                AniListTracker(credentials, db=db),
                MyAnimeListTracker(credentials, db=db),
            ])
            _manager.credentials = credentials
        return _manager


__all__ = [
    "DEFAULT_PULL_INTERVAL",
    "READ_THRESHOLD",
    "TrackManager",
    "get_track_manager",
]
