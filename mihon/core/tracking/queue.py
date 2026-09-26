"""
Persistent retry queue for tracker updates.

A sync fires the moment a chapter is read, which is exactly when the network
is least reliable — offline on a laptop, or a tracker having a bad day. The
update is written here first, so it survives an app restart and is delivered
when connectivity comes back.

Backoff is exponential with a cap, and an entry that has failed too many times
is dropped rather than retried forever.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("tracking.queue")

MAX_ATTEMPTS = 8
BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 6 * 60 * 60  # 6 hours


def backoff_for(attempts: int) -> float:
    """Seconds to wait before retry number ``attempts``."""
    if attempts <= 0:
        return 0.0
    delay = BASE_BACKOFF_SECONDS * (2 ** (attempts - 1))
    return float(min(delay, MAX_BACKOFF_SECONDS))


@dataclass
class QueuedUpdate:
    id: int
    manga_id: int
    provider: str
    payload: dict
    attempts: int = 0
    last_error: str = ""
    queued_at: float = 0.0
    next_attempt_at: float = 0.0


class TrackingQueue:
    """Pending tracker updates, backed by the ``tracking_queue`` table."""

    def __init__(self, db):
        self._db = db

    # ── Writing ───────────────────────────────────────────────────────────

    def enqueue(self, manga_id: int, provider: str, payload: dict) -> int:
        """
        Queue an update, replacing any pending one for the same manga.

        Only the latest state matters — an update to chapter 12 makes a
        pending update to chapter 11 irrelevant — so a queue of stale
        progress never builds up.
        """
        now = time.time()
        self._db.conn.execute(
            "DELETE FROM tracking_queue WHERE manga_id=? AND provider=?",
            (manga_id, provider),
        )
        cursor = self._db.conn.execute(
            """
            INSERT INTO tracking_queue(
                manga_id, provider, payload, attempts, last_error,
                queued_at, next_attempt_at
            ) VALUES(?,?,?,0,'',?,?)
            """,
            (manga_id, provider, json.dumps(payload), now, now),
        )
        self._db.conn.commit()
        return cursor.lastrowid

    def mark_failed(self, queued_id: int, error: str) -> bool:
        """
        Record a failed attempt and schedule the next one.

        Returns whether the entry is still queued; False means it exhausted
        its attempts and was dropped.
        """
        row = self._db.conn.execute(
            "SELECT attempts FROM tracking_queue WHERE id=?", (queued_id,)
        ).fetchone()
        if row is None:
            return False

        attempts = int(row["attempts"]) + 1
        if attempts >= MAX_ATTEMPTS:
            logger.warning(
                "dropping tracker update %s after %d attempts: %s",
                queued_id, attempts, error,
            )
            self.remove(queued_id)
            return False

        self._db.conn.execute(
            """
            UPDATE tracking_queue
            SET attempts=?, last_error=?, next_attempt_at=?
            WHERE id=?
            """,
            (attempts, error[:500], time.time() + backoff_for(attempts), queued_id),
        )
        self._db.conn.commit()
        return True

    def remove(self, queued_id: int):
        self._db.conn.execute("DELETE FROM tracking_queue WHERE id=?", (queued_id,))
        self._db.conn.commit()

    def clear(self, manga_id: Optional[int] = None, provider: Optional[str] = None):
        """Drop pending updates, optionally narrowed to one manga or provider."""
        clauses, params = [], []
        if manga_id is not None:
            clauses.append("manga_id=?")
            params.append(manga_id)
        if provider is not None:
            clauses.append("provider=?")
            params.append(provider)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        self._db.conn.execute(f"DELETE FROM tracking_queue{where}", tuple(params))
        self._db.conn.commit()

    # ── Reading ───────────────────────────────────────────────────────────

    def due(self, now: Optional[float] = None) -> List[QueuedUpdate]:
        """Entries whose backoff has elapsed, oldest first."""
        now = time.time() if now is None else now
        rows = self._db.conn.execute(
            """
            SELECT * FROM tracking_queue
            WHERE next_attempt_at <= ?
            ORDER BY queued_at
            """,
            (now,),
        ).fetchall()
        return [self._row_to_update(row) for row in rows]

    def all(self) -> List[QueuedUpdate]:
        rows = self._db.conn.execute(
            "SELECT * FROM tracking_queue ORDER BY queued_at"
        ).fetchall()
        return [self._row_to_update(row) for row in rows]

    def count(self) -> int:
        row = self._db.conn.execute(
            "SELECT COUNT(*) AS n FROM tracking_queue"
        ).fetchone()
        return int(row["n"]) if row else 0

    @staticmethod
    def _row_to_update(row) -> QueuedUpdate:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            payload = {}
        return QueuedUpdate(
            id=row["id"],
            manga_id=row["manga_id"],
            provider=row["provider"],
            payload=payload,
            attempts=row["attempts"] or 0,
            last_error=row["last_error"] or "",
            queued_at=row["queued_at"] or 0.0,
            next_attempt_at=row["next_attempt_at"] or 0.0,
        )


__all__ = [
    "BASE_BACKOFF_SECONDS",
    "MAX_ATTEMPTS",
    "MAX_BACKOFF_SECONDS",
    "QueuedUpdate",
    "TrackingQueue",
    "backoff_for",
]
