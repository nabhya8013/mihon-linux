"""
Base Extension class for Mihon Linux.
All manga sources implement this interface.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from ..core.models import Manga, Chapter, Page, SearchFilter, ExtensionInfo


class Extension(ABC):
    """Base class for all manga source extensions."""

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
