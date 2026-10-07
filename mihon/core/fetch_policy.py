"""
When to go back to a source and when to trust what is already stored.

Android Mihon fetches details only for a manga that is not initialized and the
chapter list only when none is stored, then leaves everything else to library
updates and pull-to-refresh. This keeps that behaviour and adds an age limit,
so a copy that has sat for a day is refreshed on the next visit while one
fetched minutes ago is not fetched again.

The functions are pure so the rules can be tested without a database or a
network.
"""
from __future__ import annotations

import time
from typing import Optional

from .models import Manga

# A chapter list grows as a series updates, so it expires sooner than details.
CHAPTER_TTL_SECONDS = 60 * 60
DETAILS_TTL_SECONDS = 24 * 60 * 60


def _stale(fetched_at: Optional[float], ttl: float, now: float) -> bool:
    if fetched_at is None:
        return True
    # A timestamp in the future means the clock moved; refetch rather than
    # trust a value that cannot be aged.
    if fetched_at > now:
        return True
    return (now - fetched_at) >= ttl


def needs_details(manga: Manga, *, now: Optional[float] = None, force: bool = False) -> bool:
    """True when the details call should run for ``manga``."""
    if force or not manga.initialized or manga.id is None:
        return True
    return _stale(manga.details_fetched_at, DETAILS_TTL_SECONDS, now if now is not None else time.time())


def needs_chapters(
    manga: Manga,
    *,
    cached_count: int,
    cacheable: bool = True,
    now: Optional[float] = None,
    force: bool = False,
) -> bool:
    """True when the chapter list should be fetched for ``manga``."""
    if force or not cacheable or cached_count == 0:
        return True
    return _stale(manga.chapters_fetched_at, CHAPTER_TTL_SECONDS, now if now is not None else time.time())
