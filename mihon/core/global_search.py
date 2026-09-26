"""
Concurrent search across every installed source.

Android Mihon fans a global search out to all installed extensions at once
and renders a grid per source as each one answers, so a fast source appears
immediately instead of queueing behind a slow one. This module is that fan-out
for the desktop client.

It is deliberately free of GTK: results are delivered through plain callbacks
invoked on worker threads, and the caller is responsible for marshalling them
onto the main loop with ``GLib.idle_add``.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from .models import SearchFilter

logger = logging.getLogger("global_search")

# One slow source must not hold up the whole search.
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_WORKERS = 8
DEFAULT_LIMIT_PER_SOURCE = 20

STATUS_PENDING = "pending"
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"


@dataclass
class SourceResult:
    """What one source returned for a global search."""

    source_id: str
    source_name: str
    status: str = STATUS_PENDING
    manga: List = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_OK, STATUS_EMPTY)

    @property
    def count(self) -> int:
        return len(self.manga)


class GlobalSearch:
    """
    Runs one query against many sources in parallel.

    ``run()`` blocks until every source has answered or timed out, so call it
    from a background thread. ``on_source_done`` fires once per source, as
    soon as that source answers, which is what lets the UI fill in
    progressively.
    """

    def __init__(
        self,
        sources: Sequence,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_workers: int = DEFAULT_MAX_WORKERS,
        limit_per_source: int = DEFAULT_LIMIT_PER_SOURCE,
    ):
        self._sources = list(sources or [])
        self.timeout = float(timeout)
        self.max_workers = max(1, int(max_workers))
        self.limit_per_source = max(1, int(limit_per_source))
        self._cancelled = threading.Event()

    # ── Control ───────────────────────────────────────────────────────────

    def cancel(self):
        """
        Stop delivering results.

        Sources already in flight cannot be interrupted — the extension API is
        blocking — but their results are dropped and no further callback runs.
        """
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def source_count(self) -> int:
        return len(self._sources)

    # ── Execution ─────────────────────────────────────────────────────────

    def run(
        self,
        query: str,
        *,
        on_source_done: Optional[Callable[[SourceResult], None]] = None,
        on_complete: Optional[Callable[[List[SourceResult]], None]] = None,
    ) -> List[SourceResult]:
        """Search every source and return one SourceResult per source."""
        results = {}
        for source in self._sources:
            source_id = getattr(source, "id", "") or ""
            results[source_id] = SourceResult(
                source_id=source_id,
                source_name=getattr(source, "name", "") or source_id,
            )

        if not self._sources:
            if on_complete:
                on_complete([])
            return []

        # Deliberately not a `with` block: ThreadPoolExecutor.__exit__ calls
        # shutdown(wait=True), which would block on the very source the
        # timeout exists to escape.
        pool = ThreadPoolExecutor(max_workers=self.max_workers)
        try:
            futures = {
                pool.submit(self._search_one, source, query): source
                for source in self._sources
            }

            try:
                # The timeout is a deadline for the whole fan-out. Because the
                # sources run in parallel, that is also each source's budget.
                for future in as_completed(futures, timeout=self.timeout):
                    source = futures[future]
                    result = self._collect(future, source)
                    results[result.source_id] = result
                    if not self._cancelled.is_set() and on_source_done:
                        self._safe_call(on_source_done, result)
            except TimeoutError:
                for future, source in futures.items():
                    if future.done():
                        continue
                    source_id = getattr(source, "id", "") or ""
                    result = results[source_id]
                    result.status = STATUS_TIMEOUT
                    result.error = f"No response within {self.timeout:g}s"
                    if not self._cancelled.is_set() and on_source_done:
                        self._safe_call(on_source_done, result)
        finally:
            # A source that has already blocked cannot be interrupted — the
            # extension API is synchronous — but its worker is left to finish
            # on its own rather than held onto here. The HTTP client's own
            # timeout bounds how long that can last.
            pool.shutdown(wait=False, cancel_futures=True)

        ordered = list(results.values())
        if not self._cancelled.is_set() and on_complete:
            self._safe_call(on_complete, ordered)
        return ordered

    # ── Internals ─────────────────────────────────────────────────────────

    def _search_one(self, source, query: str):
        if self._cancelled.is_set():
            return []
        manga, _has_next = source.search(SearchFilter(query=query), 1)
        return list(manga or [])[: self.limit_per_source]

    def _collect(self, future, source) -> SourceResult:
        source_id = getattr(source, "id", "") or ""
        result = SourceResult(
            source_id=source_id,
            source_name=getattr(source, "name", "") or source_id,
        )
        try:
            manga = future.result()
        except Exception as exc:
            result.status = STATUS_ERROR
            result.error = str(exc)
            logger.warning("global search failed for %s: %s", source_id, exc)
            return result

        # Sources are inconsistent about filling these in, and the library
        # cannot store a manga without both.
        for item in manga:
            if not getattr(item, "source_id", ""):
                item.source_id = source_id
            if not getattr(item, "source_manga_id", ""):
                item.source_manga_id = getattr(item, "url", "") or item.title

        result.manga = manga
        result.status = STATUS_OK if manga else STATUS_EMPTY
        return result

    @staticmethod
    def _safe_call(callback, payload):
        try:
            callback(payload)
        except Exception as exc:
            logger.warning("global search callback failed: %s", exc)


def flatten(results: Sequence[SourceResult]) -> List:
    """
    Every manga from every source, deduplicated and sorted by title.

    Deduplication is by ``(source_id, source_manga_id)`` — the same title on
    two different sources is two distinct entries, which is the whole point of
    a migration search.
    """
    seen = set()
    flat = []
    for result in results:
        for manga in result.manga:
            key = (
                getattr(manga, "source_id", "") or result.source_id,
                getattr(manga, "source_manga_id", "")
                or getattr(manga, "url", "")
                or (manga.title or "").lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            flat.append(manga)
    flat.sort(key=lambda m: (m.title or "").lower())
    return flat


__all__ = [
    "DEFAULT_LIMIT_PER_SOURCE",
    "DEFAULT_MAX_WORKERS",
    "DEFAULT_TIMEOUT",
    "GlobalSearch",
    "STATUS_EMPTY",
    "STATUS_ERROR",
    "STATUS_OK",
    "STATUS_PENDING",
    "STATUS_TIMEOUT",
    "SourceResult",
    "flatten",
]
