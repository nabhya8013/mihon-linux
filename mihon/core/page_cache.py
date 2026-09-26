"""
Sliding-window page prefetching for the reader.

Android Mihon keeps a dual-directional window of decoded pages around the one
being read, so a page turn is instant even on a slow connection. This module
is the same idea: :class:`PageCache` is told which page is on screen, and it
warms a configurable number of pages ahead and behind while dropping anything
that falls outside that window.

The cache holds no pixbufs itself. It drives
:mod:`mihon.core.image_loader`, which owns the decoded images, so a page the
window has warmed is served from memory the moment the reader asks for it.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence

logger = logging.getLogger("page_cache")

# Pages kept warm on either side of the current one. Forward is larger
# because reading moves forward; backward covers a page turn taken back.
DEFAULT_AHEAD = 3
DEFAULT_BEHIND = 2


def page_url(page) -> str:
    """The URL the loader would fetch for a page, or "" for a local file."""
    if page is None:
        return ""
    if getattr(page, "local_path", ""):
        return ""
    return getattr(page, "image_url", "") or getattr(page, "url", "") or ""


class PageCache:
    """
    Keeps a window of pages warm around the current index.

    ``prefetch`` and ``evict`` are injected so this class can be tested
    without GTK or the network. They default to the real image loader.
    """

    def __init__(
        self,
        ahead: int = DEFAULT_AHEAD,
        behind: int = DEFAULT_BEHIND,
        prefetch: Optional[Callable[[str], None]] = None,
        evict: Optional[Callable[[str], None]] = None,
    ):
        self.ahead = max(0, int(ahead))
        self.behind = max(0, int(behind))
        self._pages: List = []
        self._warm: set = set()
        self._current: Optional[int] = None

        if prefetch is None or evict is None:
            from . import image_loader
            prefetch = prefetch or image_loader.prefetch
            evict = evict or image_loader.evict

        self._prefetch = prefetch
        self._evict = evict

    # ── Configuration ─────────────────────────────────────────────────────

    def set_window(self, ahead: int, behind: int):
        """Resize the window. Takes effect on the next focus()."""
        self.ahead = max(0, int(ahead))
        self.behind = max(0, int(behind))

    @property
    def window_size(self) -> int:
        """How many pages the window covers, including the current one."""
        return self.ahead + self.behind + 1

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def set_pages(self, pages: Sequence):
        """Start on a new chapter. Drops everything the old one had warm."""
        self.clear()
        self._pages = list(pages or [])

    def clear(self):
        """Evict every page this cache warmed and forget the chapter."""
        for url in list(self._warm):
            self._safe_evict(url)
        self._warm.clear()
        self._pages = []
        self._current = None

    # ── Window ────────────────────────────────────────────────────────────

    def window_indices(self, index: int) -> List[int]:
        """
        Page indices the window covers, current page first.

        Ordering matters: the loader works through prefetch calls roughly in
        the order they arrive, and the pages just ahead are needed soonest.
        """
        if not self._pages:
            return []

        last = len(self._pages) - 1
        index = max(0, min(int(index), last))

        indices = [index]
        for step in range(1, max(self.ahead, self.behind) + 1):
            forward = index + step
            if step <= self.ahead and forward <= last:
                indices.append(forward)
            backward = index - step
            if step <= self.behind and backward >= 0:
                indices.append(backward)
        return indices

    def focus(self, index: int):
        """
        Move the window to ``index``: warm what is inside it, drop what left.

        Safe to call on every page turn — pages already warm are not
        re-fetched.
        """
        if not self._pages:
            return

        self._current = index
        wanted_indices = self.window_indices(index)
        wanted_urls = set()
        for i in wanted_indices:
            url = page_url(self._pages[i])
            if url:
                wanted_urls.add(url)

        # Evict first so a large chapter does not briefly hold two windows.
        for url in list(self._warm):
            if url not in wanted_urls:
                self._safe_evict(url)
                self._warm.discard(url)

        for i in wanted_indices:
            url = page_url(self._pages[i])
            if not url or url in self._warm:
                continue
            self._safe_prefetch(url)
            self._warm.add(url)

    # ── Introspection, used by the tests ──────────────────────────────────

    @property
    def warm_urls(self) -> set:
        return set(self._warm)

    @property
    def current_index(self) -> Optional[int]:
        return self._current

    # ── Internals ─────────────────────────────────────────────────────────

    def _safe_prefetch(self, url: str):
        try:
            self._prefetch(url)
        except Exception as exc:
            logger.warning("prefetch failed for %s: %s", url, exc)

    def _safe_evict(self, url: str):
        try:
            self._evict(url)
        except Exception as exc:
            logger.warning("evict failed for %s: %s", url, exc)


# ── Double-page spread detection ──────────────────────────────────────────

# A page whose width exceeds its height by this factor is a two-page spread
# scanned as one image, so it takes the whole viewport in double-page mode.
SPREAD_ASPECT_RATIO = 1.3

# Below this window width, double-page mode has no room to be useful.
AUTO_DOUBLE_MIN_WIDTH = 1600


def is_spread(width: int, height: int, ratio: float = SPREAD_ASPECT_RATIO) -> bool:
    """True when an image is wide enough to be a full two-page spread."""
    if not width or not height or height <= 0:
        return False
    return (width / height) >= ratio


def pixbuf_is_spread(pixbuf, ratio: float = SPREAD_ASPECT_RATIO) -> bool:
    """is_spread() for a GdkPixbuf, tolerating None."""
    if pixbuf is None:
        return False
    try:
        return is_spread(pixbuf.get_width(), pixbuf.get_height(), ratio)
    except Exception:
        return False


def should_auto_double(window_width: int, min_width: int = AUTO_DOUBLE_MIN_WIDTH) -> bool:
    """True when a window is wide enough to switch to double-page by itself."""
    return int(window_width or 0) >= int(min_width)


__all__ = [
    "AUTO_DOUBLE_MIN_WIDTH",
    "DEFAULT_AHEAD",
    "DEFAULT_BEHIND",
    "PageCache",
    "SPREAD_ASPECT_RATIO",
    "is_spread",
    "page_url",
    "pixbuf_is_spread",
    "should_auto_double",
]
