"""
Export the local library to a Mihon Android backup (.tachibk).

This is the inverse of :mod:`mihon.core.tachibk_importer`. It reuses that
module's protobuf descriptor so both directions stay pinned to the same
schema: whatever field numbers the importer reads, the exporter writes.

The output is a gzipped ``MihonBackup.Backup`` message, which is exactly what
Android Mihon's *Settings -> Data and storage -> Create backup* produces, so a
file written here can be restored on a phone.

Two details make the round trip work:

Source IDs
    Android identifies a source by a 64-bit number derived from its name,
    language and version (see :func:`tachiyomi_source_id`). Manga imported
    from a ``.tachibk`` keep that number in ``source_id`` as ``"mihon:<id>"``
    and are written back verbatim. Manga added from a built-in Python source
    get the same hash computed from the source's own name and language, so
    Android resolves them to the matching installed extension.

Timestamps
    The local database stores epoch **seconds** as floats; the backup format
    stores epoch **milliseconds** as int64.
"""
from __future__ import annotations

import gzip
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from .database import get_db
from .models import Chapter, Manga
from .source_ids import to_android_id as resolve_source_id, tachiyomi_source_id
from .tachibk_importer import _ensure_message_classes
from .backup_mapping import tracking_to_backup, viewer_flags_for_reading_mode
from .tracking.base import TrackEntry

logger = logging.getLogger("tachibk_exporter")

# Inverse of tachibk_importer._status_to_string. Anything unrecognised
# becomes 0 (Unknown), which is what Android does for an unset status.
_STATUS_TO_INT = {
    "ongoing": 1,
    "completed": 2,
    "licensed": 3,
    "publishing finished": 4,
    "publishing_finished": 4,
    "cancelled": 5,
    "canceled": 5,
    "on hiatus": 6,
    "on_hiatus": 6,
    "hiatus": 6,
}

def _to_millis(seconds: Optional[float]) -> int:
    if not seconds:
        return 0
    return int(seconds * 1000)


@dataclass
class ExportResult:
    path: Optional[Path] = None
    exported_manga: int = 0
    exported_chapters: int = 0
    exported_categories: int = 0
    bytes_written: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.path is not None

    def summary(self) -> str:
        if not self.ok:
            return "Export failed: " + ("; ".join(self.errors) or "unknown error")
        return (
            f"Exported {self.exported_manga} manga, "
            f"{self.exported_chapters} chapters, "
            f"{self.exported_categories} categories "
            f"({self.bytes_written} bytes)"
        )


def _fill_chapter(proto_chapter, chapter: Chapter, source_order: int) -> None:
    proto_chapter.url = chapter.url or chapter.source_chapter_id or ""
    proto_chapter.name = chapter.title or ""
    proto_chapter.scanlator = chapter.scanlator or ""
    proto_chapter.read = bool(chapter.read)
    proto_chapter.lastPageRead = int(chapter.last_page_read or 0)
    proto_chapter.dateFetch = _to_millis(chapter.fetched_at)
    proto_chapter.dateUpload = _to_millis(chapter.uploaded_at)
    proto_chapter.chapterNumber = float(chapter.chapter_number or -1.0)
    proto_chapter.sourceOrder = source_order


def _fill_tracking(proto_manga, tracking_rows) -> None:
    for row in tracking_rows:
        record = tracking_to_backup(TrackEntry(
            provider=row.get("provider") or "",
            remote_id=str(row.get("remote_id") or ""),
            library_id=str(row.get("library_id") or ""),
            title=row.get("title") or "",
            status=row.get("status") or "",
            progress=float(row.get("progress") or 0),
            score=float(row.get("score") or 0),
            total_chapters=float(row.get("total_chapters") or 0),
            url=row.get("url") or "",
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
        ))
        if record is None:
            continue
        t = proto_manga.tracking.add()
        t.syncId = record["sync_id"]
        t.libraryId = record["library_id"]
        t.mediaId = record["media_id"]
        t.trackingUrl = record["url"]
        t.title = record["title"]
        t.lastChapterRead = record["last_chapter_read"]
        t.totalChapters = record["total_chapters"]
        t.score = record["score"]
        t.status = record["status"]
        t.startedReadingDate = record["started"]
        t.finishedReadingDate = record["finished"]


def _fill_manga(proto_manga, manga: Manga, chapters, category_orders,
                tracking_rows=(), reading_mode: str = "") -> int:
    proto_manga.source = resolve_source_id(manga.source_id)
    proto_manga.url = manga.source_manga_id or manga.url or ""
    proto_manga.title = manga.title or ""
    proto_manga.author = manga.author or ""
    proto_manga.artist = manga.artist or ""
    proto_manga.description = manga.description or ""
    proto_manga.genre.extend(manga.genres or [])
    proto_manga.status = _STATUS_TO_INT.get((manga.status or "").lower(), 0)
    proto_manga.thumbnailUrl = manga.cover_url or ""
    proto_manga.dateAdded = _to_millis(manga.added_at or time.time())
    proto_manga.favorite = bool(manga.in_library)
    proto_manga.categories.extend(category_orders)
    if reading_mode:
        proto_manga.viewer_flags = viewer_flags_for_reading_mode(reading_mode)
    _fill_tracking(proto_manga, tracking_rows)

    for source_order, chapter in enumerate(chapters):
        _fill_chapter(proto_manga.chapters.add(), chapter, source_order)

    if manga.last_read_at:
        # Android keys history by chapter url. The most recently read chapter
        # is the only one the local schema can attribute a timestamp to.
        last_read_chapter = next(
            (c for c in reversed(chapters) if c.read or c.last_page_read), None
        )
        if last_read_chapter is not None:
            entry = proto_manga.history.add()
            entry.url = last_read_chapter.url or last_read_chapter.source_chapter_id or ""
            entry.lastRead = _to_millis(manga.last_read_at)

    return len(chapters)


def build_backup(manga_list: Optional[Iterable[Manga]] = None):
    """
    Build the ``Backup`` protobuf message for the current library.

    Pass ``manga_list`` to export a subset; the default is every manga
    flagged ``in_library``.
    """
    backup_cls = _ensure_message_classes()
    db = get_db()
    backup = backup_cls()

    categories = db.get_categories()
    # Android matches a manga's `categories` entries against category *order*,
    # not against the row id, so build the same mapping the importer reads.
    order_by_category_id = {}
    for order, category in enumerate(categories):
        proto_category = backup.backupCategories.add()
        proto_category.name = category.name
        proto_category.order = order
        proto_category.id = order
        order_by_category_id[category.id] = order

    if manga_list is None:
        manga_list = db.get_library()

    seen_sources = {}
    total_chapters = 0

    for manga in manga_list:
        chapters = db.get_chapters(manga.id) if manga.id else []
        # Backups store chapters in source order; the library query returns
        # them newest-first, so reverse to get oldest-first.
        chapters = list(reversed(chapters))

        category_orders = [
            order_by_category_id[cid]
            for cid in (db.get_manga_category_ids(manga.id) if manga.id else [])
            if cid in order_by_category_id
        ]

        proto_manga = backup.backupManga.add()
        total_chapters += _fill_manga(
            proto_manga, manga, chapters, category_orders,
            tracking_rows=db.get_manga_tracking(manga.id) if manga.id else (),
            reading_mode=db.get_manga_reading_mode(manga.id) if manga.id else "",
        )

        seen_sources.setdefault(proto_manga.source, manga.source_id or "")

    for source_id, name in seen_sources.items():
        proto_source = backup.backupSources.add()
        proto_source.name = name
        proto_source.sourceId = source_id

    return backup, total_chapters, len(categories)


def export_tachibk(
    path: Path,
    *,
    manga_list: Optional[Iterable[Manga]] = None,
) -> ExportResult:
    """Write the library to ``path`` as a gzipped .tachibk backup."""
    path = Path(path)
    try:
        backup, total_chapters, total_categories = build_backup(manga_list)
    except Exception as exc:
        logger.exception("Failed to build backup")
        return ExportResult(errors=[f"Failed to build backup: {exc}"])

    try:
        raw = backup.SerializeToString()
        path.parent.mkdir(parents=True, exist_ok=True)
        # mtime=0 keeps the output byte-identical for identical input, which
        # makes the round-trip test deterministic.
        with path.open("wb") as fh:
            with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
                gz.write(raw)
    except Exception as exc:
        logger.exception("Failed to write backup to %s", path)
        return ExportResult(errors=[f"Failed to write backup: {exc}"])

    return ExportResult(
        path=path,
        exported_manga=len(backup.backupManga),
        exported_chapters=total_chapters,
        exported_categories=total_categories,
        bytes_written=path.stat().st_size,
    )


def default_backup_name() -> str:
    """Filename Android Mihon would use for a fresh backup."""
    return time.strftime("mihon_%Y-%m-%d_%H-%M.tachibk")


__all__ = [
    "ExportResult",
    "build_backup",
    "default_backup_name",
    "export_tachibk",
    "resolve_source_id",
    "tachiyomi_source_id",
]
