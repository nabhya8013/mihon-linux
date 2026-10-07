"""
Translate between Mihon's backup codes and this app's values.

A `.tachibk` stores trackers and reading modes as Android Mihon's own
numbers. These tables mirror the constants in Mihon's source:

- Tracker ids from `TrackerManager`: MyAnimeList is 1, AniList is 2. Other
  trackers (Kitsu, Shikimori, ...) are not supported here and are skipped.
- Status codes are per tracker (`Anilist.kt`, `MyAnimeList.kt`): the two
  agree up to 4 and then differ for plan-to-read and rereading.
- Scores: Mihon keeps AniList scores on a 100-point scale and MyAnimeList
  on 10; this app uses 10 for both.
- Reading mode is the low three bits of `viewer_flags` (`ReadingMode`):
  0 default, 1 left to right, 2 right to left, 3 vertical, 4 webtoon,
  5 continuous vertical. The higher bits hold screen orientation and are
  passed through untouched.
"""
from __future__ import annotations

from typing import Optional

from .tracking.base import (
    STATUS_COMPLETED,
    STATUS_DROPPED,
    STATUS_ON_HOLD,
    STATUS_PLAN_TO_READ,
    STATUS_READING,
    STATUS_REREADING,
    TrackEntry,
)

SYNC_ID_TO_PROVIDER = {1: "myanimelist", 2: "anilist"}
PROVIDER_TO_SYNC_ID = {provider: sync_id for sync_id, provider in SYNC_ID_TO_PROVIDER.items()}

_STATUS_CODES = {
    "anilist": {
        1: STATUS_READING,
        2: STATUS_COMPLETED,
        3: STATUS_ON_HOLD,
        4: STATUS_DROPPED,
        5: STATUS_PLAN_TO_READ,
        6: STATUS_REREADING,
    },
    "myanimelist": {
        1: STATUS_READING,
        2: STATUS_COMPLETED,
        3: STATUS_ON_HOLD,
        4: STATUS_DROPPED,
        6: STATUS_PLAN_TO_READ,
        7: STATUS_REREADING,
    },
}
_STATUS_TO_CODE = {
    provider: {status: code for code, status in codes.items()}
    for provider, codes in _STATUS_CODES.items()
}

# Multiply this app's 0-10 score by this to get Mihon's stored score.
_SCORE_SCALE = {"anilist": 10.0, "myanimelist": 1.0}

READING_MODE_MASK = 0x7
_VIEWER_TO_MODE = {1: "ltr", 2: "rtl", 3: "webtoon", 4: "webtoon", 5: "webtoon"}
_MODE_TO_VIEWER = {"ltr": 1, "rtl": 2, "webtoon": 4}


def tracking_from_backup(record: dict) -> Optional[TrackEntry]:
    """A TrackEntry for one backup tracking record, or None for an unsupported tracker."""
    provider = SYNC_ID_TO_PROVIDER.get(int(record.get("sync_id") or 0))
    if provider is None:
        return None
    started = record.get("started") or 0
    finished = record.get("finished") or 0
    return TrackEntry(
        provider=provider,
        remote_id=str(record.get("media_id") or ""),
        library_id=str(record.get("library_id") or "") if record.get("library_id") else "",
        title=record.get("title") or "",
        status=_STATUS_CODES[provider].get(int(record.get("status") or 0), STATUS_READING),
        progress=float(record.get("last_chapter_read") or 0),
        score=float(record.get("score") or 0) / _SCORE_SCALE[provider],
        total_chapters=float(record.get("total_chapters") or 0),
        url=record.get("url") or "",
        started_at=started / 1000.0 if started else None,
        finished_at=finished / 1000.0 if finished else None,
    )


def tracking_to_backup(entry: TrackEntry) -> Optional[dict]:
    """The backup record for a TrackEntry, or None for an unsupported tracker."""
    sync_id = PROVIDER_TO_SYNC_ID.get(entry.provider)
    if sync_id is None:
        return None
    try:
        media_id = int(entry.remote_id or 0)
    except ValueError:
        return None
    try:
        library_id = int(entry.library_id or 0)
    except ValueError:
        library_id = 0
    return {
        "sync_id": sync_id,
        "library_id": library_id,
        "media_id": media_id,
        "url": entry.url or "",
        "title": entry.title or "",
        "last_chapter_read": float(entry.progress or 0),
        "total_chapters": int(entry.total_chapters or 0),
        "score": float(entry.score or 0) * _SCORE_SCALE[entry.provider],
        "status": _STATUS_TO_CODE[entry.provider].get(entry.status, 1),
        "started": int((entry.started_at or 0) * 1000),
        "finished": int((entry.finished_at or 0) * 1000),
    }


def reading_mode_from_viewer_flags(flags: int) -> str:
    """"ltr", "rtl", "webtoon", or "" for the reader default."""
    return _VIEWER_TO_MODE.get(int(flags or 0) & READING_MODE_MASK, "")


def viewer_flags_for_reading_mode(mode: str, existing_flags: int = 0) -> int:
    """Set the reading-mode bits of ``existing_flags`` and keep the rest."""
    code = _MODE_TO_VIEWER.get(mode or "", 0)
    return (int(existing_flags or 0) & ~READING_MODE_MASK) | code


__all__ = [
    "PROVIDER_TO_SYNC_ID",
    "SYNC_ID_TO_PROVIDER",
    "reading_mode_from_viewer_flags",
    "tracking_from_backup",
    "tracking_to_backup",
    "viewer_flags_for_reading_mode",
]
