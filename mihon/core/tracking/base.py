"""
Tracker service contract.

Mihon acts as an offline front end for online tracking platforms: reading a
chapter locally updates the entry on AniList, MyAnimeList and friends. Every
service speaks a different API, so they all implement :class:`TrackerService`
and the rest of the app only sees this interface.

Status values are normalised here. Each service maps them onto whatever its
own API calls the same thing.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("tracking")

# Normalised reading states, matching the set Mihon uses.
STATUS_READING = "reading"
STATUS_COMPLETED = "completed"
STATUS_ON_HOLD = "on_hold"
STATUS_DROPPED = "dropped"
STATUS_PLAN_TO_READ = "plan_to_read"
STATUS_REREADING = "rereading"

ALL_STATUSES = (
    STATUS_READING,
    STATUS_COMPLETED,
    STATUS_ON_HOLD,
    STATUS_DROPPED,
    STATUS_PLAN_TO_READ,
    STATUS_REREADING,
)

STATUS_LABELS = {
    STATUS_READING: "Reading",
    STATUS_COMPLETED: "Completed",
    STATUS_ON_HOLD: "On hold",
    STATUS_DROPPED: "Dropped",
    STATUS_PLAN_TO_READ: "Plan to read",
    STATUS_REREADING: "Rereading",
}


class TrackerError(Exception):
    """A tracker call failed."""


class TrackerAuthError(TrackerError):
    """
    The stored credentials are missing, expired or rejected.

    Distinct from a transient failure: retrying will not help until the user
    logs in again, so the retry queue drops these instead of looping.
    """


@dataclass
class TrackSearchResult:
    """One candidate when linking a local manga to a remote entry."""

    remote_id: str
    title: str
    cover_url: str = ""
    total_chapters: float = 0.0
    summary: str = ""
    url: str = ""
    publishing_status: str = ""
    start_date: str = ""
    score: float = 0.0


@dataclass
class TrackEntry:
    """The state of one manga on one tracking service."""

    provider: str = ""
    remote_id: str = ""
    library_id: str = ""
    title: str = ""
    status: str = STATUS_READING
    progress: float = 0.0
    score: float = 0.0
    total_chapters: float = 0.0
    url: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def with_progress(self, chapter_number: float) -> "TrackEntry":
        """
        A copy advanced to ``chapter_number``.

        Progress never moves backwards — rereading an earlier chapter must not
        wipe out what the user has already read — and reaching the last
        chapter marks the entry completed, which is what Android does.
        """
        entry = TrackEntry(**self.__dict__)
        if chapter_number > entry.progress:
            entry.progress = float(chapter_number)
        if (
            entry.total_chapters
            and entry.progress >= entry.total_chapters
            and entry.status in (STATUS_READING, STATUS_REREADING)
        ):
            entry.status = STATUS_COMPLETED
        elif entry.status == STATUS_PLAN_TO_READ and entry.progress > 0:
            entry.status = STATUS_READING
        return entry


class TrackerService(ABC):
    """
    One tracking platform.

    Implementations are responsible for their own token storage through the
    injected credential store, and must raise :class:`TrackerAuthError` when a
    call fails because the user is not (or is no longer) logged in.
    """

    #: Stable key used in the database and in settings.
    id: str = ""
    #: Shown in the UI.
    name: str = ""
    #: Highest score the service accepts, for the UI's score control.
    max_score: float = 10.0

    def __init__(self, credentials):
        self._credentials = credentials

    # ── Authentication ────────────────────────────────────────────────────

    @abstractmethod
    def authorization_url(self) -> str:
        """The URL to open in a browser to start the login flow."""

    @abstractmethod
    def complete_login(self, redirect_response: str) -> bool:
        """
        Finish login from whatever the browser handed back.

        ``redirect_response`` is the full redirect URL, or the bare token or
        code pasted by the user. Returns whether login succeeded.
        """

    @property
    def is_logged_in(self) -> bool:
        return bool(self._credentials.get_token(self.id))

    def logout(self):
        self._credentials.clear(self.id)

    # ── Data ──────────────────────────────────────────────────────────────

    @abstractmethod
    def search(self, query: str) -> List[TrackSearchResult]:
        """Find remote entries matching a title."""

    @abstractmethod
    def bind(self, remote_id: str) -> TrackEntry:
        """
        Add the remote entry to the user's list, or fetch it if already there.

        Returns the entry as it now stands remotely.
        """

    @abstractmethod
    def update(self, entry: TrackEntry) -> TrackEntry:
        """Push progress, status and score to the service."""

    @abstractmethod
    def refresh(self, entry: TrackEntry) -> TrackEntry:
        """Pull the remote entry's current state back down."""


__all__ = [
    "ALL_STATUSES",
    "STATUS_COMPLETED",
    "STATUS_DROPPED",
    "STATUS_LABELS",
    "STATUS_ON_HOLD",
    "STATUS_PLAN_TO_READ",
    "STATUS_READING",
    "STATUS_REREADING",
    "TrackEntry",
    "TrackSearchResult",
    "TrackerAuthError",
    "TrackerError",
    "TrackerService",
]
