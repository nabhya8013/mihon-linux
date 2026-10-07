"""
Base Extension class for Mihon Linux.
All manga sources implement this interface.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from ..core.models import Manga, Chapter, Page, SearchFilter, ExtensionInfo


def apply_source_order(chapters: List[Chapter]) -> List[Chapter]:
    """
    Fill in ``source_order`` from the order a source listed its chapters.

    Tachiyomi's convention is 0 for the newest chapter. Built-in sources do
    not all say which way their list runs, so the direction is read from the
    chapter numbers: mostly falling means newest first, mostly rising means
    oldest first. With no numbers to go on, newest first is assumed, as in
    Tachiyomi. Unnumbered chapters keep their place in the list, which is
    the whole point: it is the only ordering they have.
    """
    if not chapters:
        return chapters
    numbers = [c.chapter_number for c in chapters if c.chapter_number is not None and c.chapter_number >= 0]
    falling = sum(1 for a, b in zip(numbers, numbers[1:]) if b < a)
    rising = sum(1 for a, b in zip(numbers, numbers[1:]) if b > a)
    oldest_first = rising > falling
    last = len(chapters) - 1
    for index, chapter in enumerate(chapters):
        chapter.source_order = last - index if oldest_first else index
    return chapters


class Extension(ABC):
    """Base class for all manga source extensions."""

    # Whether a fetched chapter list may be reused until it goes stale. A source
    # whose listing is cheap and can change underneath us (a folder on disk)
    # sets this False so the list is read again on every visit.
    cache_chapters: bool = True

    @property
    @abstractmethod
    def info(self) -> ExtensionInfo:
        """Return metadata about this extension."""
        ...

    @property
    def id(self) -> str:
        return self.info.id

    @property
    def name(self) -> str:
        return self.info.name

    # ── Browsing ───────────────────────────────────────────────────────────

    @abstractmethod
    def get_popular(self, page: int = 1) -> Tuple[List[Manga], bool]:
        """
        Return (manga_list, has_next_page).
        page is 1-indexed.
        """
        ...

    @abstractmethod
    def get_latest(self, page: int = 1) -> Tuple[List[Manga], bool]:
        """Return latest updated manga."""
        ...

    @abstractmethod
    def search(self, filters: SearchFilter, page: int = 1) -> Tuple[List[Manga], bool]:
        """Search manga by filters."""
        ...

    # ── Details ────────────────────────────────────────────────────────────

    @abstractmethod
    def get_manga_details(self, manga: Manga) -> Manga:
        """Fetch full manga details (author, description, genres, etc.)."""
        ...

    @abstractmethod
    def get_chapters(self, manga: Manga) -> List[Chapter]:
        """Fetch chapter list for a manga."""
        ...

    @abstractmethod
    def get_pages(self, chapter: Chapter) -> List[Page]:
        """Fetch page image URLs for a chapter."""
        ...

    # ── Optional ───────────────────────────────────────────────────────────

    def get_filters(self) -> List[dict]:
        """Return available search filters for this source. Override to provide filters."""
        return []

    def has_settings(self) -> bool:
        return False

    def get_settings(self) -> dict:
        return {}

    def save_settings(self, settings: dict):
        pass
