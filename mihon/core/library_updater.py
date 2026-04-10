"""
Library updater for Mihon Linux.
Checks library manga for new chapters and updates DB counts.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .database import get_db
from .models import Manga, Chapter
from ..extensions.registry import get_registry


@dataclass
class MangaUpdateResult:
    manga: Manga
    new_chapters: List[Chapter] = field(default_factory=list)
    error: str = ""


@dataclass
class LibraryUpdateSummary:
    checked_manga: int = 0
    updated_manga: int = 0
    new_chapters: int = 0
    failures: int = 0
    results: List[MangaUpdateResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class LibraryUpdater:
    """
    Synchronizes chapter lists for all manga in the library.
    Returns only entries that received newly discovered chapters.
    """

    def __init__(self):
        self._db = get_db()

    def check_updates(
        self,
        progress_cb: Optional[Callable[[int, int, Manga], None]] = None,
    ) -> LibraryUpdateSummary:
        summary = LibraryUpdateSummary()
        registry = get_registry()

        # Ensure installed JVM extensions are available when needed.
        try:
            registry.load_jvm_extensions()
        except Exception:
            pass

        library = self._db.get_library()
        total = len(library)

        for idx, manga in enumerate(library, start=1):
            summary.checked_manga += 1

            if progress_cb:
                progress_cb(idx, total, manga)

            ext = registry.get(manga.source_id)
            if not ext:
                summary.failures += 1
                msg = f"{manga.title}: source '{manga.source_id}' is not available"
                summary.errors.append(msg)
                continue

            try:
                existing = self._db.get_chapters(manga.id)
                existing_ids = {ch.source_chapter_id for ch in existing}

                fetched = ext.get_chapters(manga)
                for ch in fetched:
                    ch.manga_id = manga.id

                new_chapters = [ch for ch in fetched if ch.source_chapter_id not in existing_ids]

                if fetched:
                    self._db.upsert_chapters(fetched)
                self._db.update_unread_count(manga.id)

                if new_chapters:
                    summary.updated_manga += 1
                    summary.new_chapters += len(new_chapters)
                    refreshed = self._db.get_manga_by_id(manga.id) or manga
                    # Keep results ordered newest-first when possible.
                    ordered_new = sorted(
                        new_chapters,
                        key=lambda c: (c.uploaded_at or 0.0, c.chapter_number),
                        reverse=True,
                    )
                    summary.results.append(
                        MangaUpdateResult(manga=refreshed, new_chapters=ordered_new)
                    )
            except Exception as e:
                summary.failures += 1
                msg = f"{manga.title}: {e}"
                summary.errors.append(msg)

        return summary
