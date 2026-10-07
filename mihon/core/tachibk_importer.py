"""
Restore a Mihon Android backup (.tachibk) into the local library.

The .tachibk format is a gzip-compressed protobuf message defined in
Mihon's `Backup` schema (BackupManga, BackupCategory, BackupChapter,
BackupTracking, BackupSource, BackupHistory, BrokenBackupSource,
BrokenBackupHistory). The .proto file is bundled inline so we can build
the descriptor dynamically with `google.protobuf` and avoid needing
`protoc` to be installed.

The importer is dry-run by default. Pass `apply=True` to write parsed
entries into the local SQLite library.
"""
from __future__ import annotations

import gzip
import io
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, text_format

from .database import get_db
from .models import Chapter, Manga, ReadingStatus
from .source_ids import to_local_id
from .backup_mapping import reading_mode_from_viewer_flags, tracking_from_backup

logger = logging.getLogger("tachibk_importer")

MIHON_BACKUP_PROTO = r"""
name: "mihon_backup.proto"
package: "MihonBackup"
message_type {
  name: "BackupManga"
  field { name: "source" number: 1 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "url" number: 2 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "title" number: 3 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "artist" number: 4 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "author" number: 5 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "description" number: 6 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "genre" number: 7 label: LABEL_REPEATED type: TYPE_STRING }
  field { name: "status" number: 8 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "thumbnailUrl" number: 9 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "dateAdded" number: 13 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "viewer" number: 14 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "chapters" number: 16 label: LABEL_REPEATED type: TYPE_MESSAGE type_name: ".MihonBackup.BackupChapter" }
  field { name: "categories" number: 17 label: LABEL_REPEATED type: TYPE_INT64 }
  field { name: "tracking" number: 18 label: LABEL_REPEATED type: TYPE_MESSAGE type_name: ".MihonBackup.BackupTracking" }
  field { name: "favorite" number: 100 label: LABEL_OPTIONAL type: TYPE_BOOL }
  field { name: "chapterFlags" number: 101 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "viewer_flags" number: 103 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "history" number: 104 label: LABEL_REPEATED type: TYPE_MESSAGE type_name: ".MihonBackup.BackupHistory" }
  field { name: "updateStrategy" number: 105 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "lastModifiedAt" number: 106 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "favoriteModifiedAt" number: 107 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "excludedScanlators" number: 108 label: LABEL_REPEATED type: TYPE_STRING }
  field { name: "version" number: 109 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "notes" number: 110 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "initialized" number: 111 label: LABEL_OPTIONAL type: TYPE_BOOL }
  field { name: "memo" number: 112 label: LABEL_OPTIONAL type: TYPE_BYTES }
}
message_type {
  name: "BackupChapter"
  field { name: "url" number: 1 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "name" number: 2 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "scanlator" number: 3 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "read" number: 4 label: LABEL_OPTIONAL type: TYPE_BOOL }
  field { name: "bookmark" number: 5 label: LABEL_OPTIONAL type: TYPE_BOOL }
  field { name: "lastPageRead" number: 6 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "dateFetch" number: 7 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "dateUpload" number: 8 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "chapterNumber" number: 9 label: LABEL_OPTIONAL type: TYPE_FLOAT }
  field { name: "sourceOrder" number: 10 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "lastModifiedAt" number: 100 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "version" number: 101 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "readNumber" number: 102 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "bookmarkNumber" number: 103 label: LABEL_OPTIONAL type: TYPE_INT32 }
}
message_type {
  name: "BackupTracking"
  field { name: "syncId" number: 1 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "libraryId" number: 2 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "mediaId" number: 3 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "trackingUrl" number: 4 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "title" number: 5 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "lastChapterRead" number: 6 label: LABEL_OPTIONAL type: TYPE_FLOAT }
  field { name: "totalChapters" number: 7 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "score" number: 8 label: LABEL_OPTIONAL type: TYPE_FLOAT }
  field { name: "status" number: 9 label: LABEL_OPTIONAL type: TYPE_INT32 }
  field { name: "startedReadingDate" number: 10 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "finishedReadingDate" number: 11 label: LABEL_OPTIONAL type: TYPE_INT64 }
}
message_type {
  name: "BackupCategory"
  field { name: "name" number: 1 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "order" number: 2 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "id" number: 3 label: LABEL_OPTIONAL type: TYPE_INT64 }
  field { name: "flags" number: 100 label: LABEL_OPTIONAL type: TYPE_INT64 }
}
message_type {
  name: "BackupSource"
  field { name: "name" number: 1 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "sourceId" number: 2 label: LABEL_OPTIONAL type: TYPE_INT64 }
}
message_type {
  name: "BackupHistory"
  field { name: "url" number: 1 label: LABEL_OPTIONAL type: TYPE_STRING }
  field { name: "lastRead" number: 2 label: LABEL_OPTIONAL type: TYPE_INT64 }
}
message_type {
  name: "Backup"
  field { name: "backupManga" number: 1 label: LABEL_REPEATED type: TYPE_MESSAGE type_name: ".MihonBackup.BackupManga" }
  field { name: "backupCategories" number: 2 label: LABEL_REPEATED type: TYPE_MESSAGE type_name: ".MihonBackup.BackupCategory" }
  field { name: "backupSources" number: 101 label: LABEL_REPEATED type: TYPE_MESSAGE type_name: ".MihonBackup.BackupSource" }
}
"""

_DESCRIPTOR_POOL: Optional[descriptor_pool.DescriptorPool] = None
_BACKUP_MESSAGE = None


def _ensure_message_classes():
    global _DESCRIPTOR_POOL, _BACKUP_MESSAGE
    if _BACKUP_MESSAGE is not None:
        return _BACKUP_MESSAGE

    file_proto = descriptor_pb2.FileDescriptorProto()
    text_format.Parse(MIHON_BACKUP_PROTO, file_proto)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    _DESCRIPTOR_POOL = pool
    _BACKUP_MESSAGE = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("MihonBackup.Backup")
    )
    return _BACKUP_MESSAGE


def _gunzip(path: Path) -> bytes:
    with path.open("rb") as f:
        magic = f.read(2)
    with path.open("rb") as f:
        if magic == b"\x1f\x8b":
            return gzip.GzipFile(fileobj=f).read()
        f.seek(0)
        return f.read()


class BackupError(Exception):
    """The file is not a usable Mihon backup. The message is safe to show."""


class ConflictMode(str, Enum):
    """
    What to do with a manga that is already in the local database.

    MERGE keeps the local copy and only adds what it lacks: missing chapters,
    categories, and read progress (read stays read, the further page wins).
    OVERWRITE replaces the local metadata and read progress with the backup's.
    Neither mode removes a manga from the library or deletes a chapter.
    """
    MERGE = "merge"
    OVERWRITE = "overwrite"


@dataclass
class RestoredManga:
    source: int
    url: str
    title: str
    author: str = ""
    artist: str = ""
    description: str = ""
    genres: List[str] = field(default_factory=list)
    status: int = 0
    thumbnail_url: str = ""
    date_added: int = 0
    favorite: bool = True
    chapter_count: int = 0
    categories: List[int] = field(default_factory=list)
    chapters: List[dict] = field(default_factory=list)
    history: List[dict] = field(default_factory=list)
    tracking: List[dict] = field(default_factory=list)
    viewer_flags: int = 0


@dataclass
class RestoredBackup:
    mangas: List[RestoredManga] = field(default_factory=list)
    categories: List[tuple] = field(default_factory=list)  # (name, order)
    sources: List[tuple] = field(default_factory=list)      # (name, source_id)
    broken_sources: List[tuple] = field(default_factory=list)
    total_bytes: int = 0


def parse_backup(path: Path) -> RestoredBackup:
    """Parse a .tachibk file into structured data without touching the DB."""
    backup_cls = _ensure_message_classes()
    try:
        raw = _gunzip(path)
        msg = backup_cls()
        msg.ParseFromString(raw)
    except Exception as exc:
        raise BackupError(f"{path.name} is not a readable Mihon backup ({exc})") from exc

    if not (msg.backupManga or msg.backupCategories or msg.backupSources):
        raise BackupError(f"{path.name} contains no library data")

    backup = RestoredBackup(total_bytes=len(raw))
    for category in msg.backupCategories:
        backup.categories.append((category.name, category.order))
    for source in msg.backupSources:
        backup.sources.append((source.name, source.sourceId))
    for manga in msg.backupManga:
        # Android Mihon uses `favorite: Boolean = true` as the Kotlin
        # default. kotlinx.serialization.protobuf omits `true` from the
        # wire format, so a missing field must be treated as `true`.
        is_favorite = True
        if hasattr(manga, "HasField") and manga.HasField("favorite"):
            is_favorite = bool(manga.favorite)

        restored = RestoredManga(
            source=manga.source,
            url=manga.url,
            title=manga.title,
            author=manga.author or "",
            artist=manga.artist or "",
            description=manga.description or "",
            genres=list(manga.genre),
            status=manga.status,
            thumbnail_url=manga.thumbnailUrl or "",
            date_added=manga.dateAdded,
            favorite=is_favorite,
            chapter_count=len(manga.chapters),
            categories=[int(c) for c in manga.categories],
            chapters=[
                {
                    "url": ch.url,
                    "name": ch.name,
                    "scanlator": ch.scanlator or "",
                    "read": ch.read,
                    "bookmark": ch.bookmark,
                    "last_page_read": ch.lastPageRead,
                    "date_fetch": ch.dateFetch,
                    "date_upload": ch.dateUpload,
                    "chapter_number": ch.chapterNumber,
                    "source_order": ch.sourceOrder,
                }
                for ch in manga.chapters
            ],
            history=[
                {"url": h.url, "last_read": h.lastRead} for h in manga.history
            ],
            tracking=[
                {
                    "sync_id": t.syncId,
                    "library_id": t.libraryId,
                    "media_id": t.mediaId,
                    "url": t.trackingUrl or "",
                    "title": t.title or "",
                    "last_chapter_read": t.lastChapterRead,
                    "total_chapters": t.totalChapters,
                    "score": t.score,
                    "status": t.status,
                    "started": t.startedReadingDate,
                    "finished": t.finishedReadingDate,
                }
                for t in manga.tracking
            ],
            viewer_flags=manga.viewer_flags,
        )
        backup.mangas.append(restored)
    return backup


def _status_to_string(status: int) -> str:
    """
    Map Android's `SManga` status enum onto the local string status.

    0 is UNKNOWN, not ONGOING — an earlier version of this map was shifted by
    one, which reported every ongoing series as completed.
    """
    return {
        0: "",
        1: "ongoing",
        2: "completed",
        3: "licensed",
        4: "publishing finished",
        5: "cancelled",
        6: "on hiatus",
    }.get(status, "")


def _manga_to_library(manga: RestoredManga) -> Manga:
    return Manga(
        # A backup this app exported carries the numeric id of a built-in
        # source, so map it back to that source's name. Otherwise re-importing
        # our own backup would add a second copy of every manga.
        source_id=to_local_id(manga.source),
        source_manga_id=manga.url,
        title=manga.title,
        alt_titles=[],
        author=manga.author,
        artist=manga.artist,
        description=manga.description,
        genres=manga.genres,
        status=_status_to_string(manga.status),
        cover_url=manga.thumbnail_url,
        url=manga.url,
        in_library=manga.favorite,
        reading_status=ReadingStatus.NONE,
        unread_count=sum(1 for c in manga.chapters if not c["read"]),
        chapter_count=manga.chapter_count,
        last_read_at=max(
            (h["last_read"] / 1000.0 for h in manga.history if h["last_read"]),
            default=None,
        ),
        added_at=(manga.date_added / 1000.0) if manga.date_added else time.time(),
    )


@dataclass
class ImportPreview:
    """What a restore would touch, computed without writing anything."""
    manga: int = 0
    categories: int = 0
    chapters: int = 0
    read_chapters: int = 0
    existing_manga: int = 0
    trackers: int = 0

    @property
    def new_manga(self) -> int:
        return self.manga - self.existing_manga


def preview_backup(path: Path) -> ImportPreview:
    """Parse ``path`` and count what a restore would do. Raises BackupError."""
    backup = parse_backup(path)
    db = get_db()
    preview = ImportPreview(
        manga=len(backup.mangas),
        categories=len([c for c in backup.categories if c[0]]),
    )
    for restored in backup.mangas:
        preview.chapters += len(restored.chapters)
        preview.read_chapters += sum(1 for c in restored.chapters if c["read"])
        preview.trackers += sum(1 for t in restored.tracking if tracking_from_backup(t) is not None)
        if db.get_manga_by_source(to_local_id(restored.source), restored.url) is not None:
            preview.existing_manga += 1
    return preview


@dataclass
class ImportResult:
    backup: Optional[RestoredBackup] = None
    applied: bool = False
    imported_manga: int = 0
    new_manga: int = 0
    imported_chapters: int = 0
    imported_categories: int = 0
    imported_trackers: int = 0
    skipped_trackers: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.backup is None:
            return "No backup loaded"
        if self.applied:
            text = (
                f"Restored {self.imported_manga} manga "
                f"({self.new_manga} new), "
                f"{self.imported_chapters} chapters, "
                f"{self.imported_categories} categories, "
                f"{self.imported_trackers} tracker links, "
                f"{len(self.errors)} errors"
            )
            if self.skipped_trackers:
                text += f" ({self.skipped_trackers} links to unsupported trackers skipped)"
            return text
        return (
            f"Parsed {len(self.backup.mangas)} manga, "
            f"{len(self.backup.categories)} categories "
            f"(dry run, no DB changes)"
        )


def _restore_chapters(db, manga_id: int, restored: RestoredManga, mode: ConflictMode) -> int:
    """
    Write one manga's chapters and read progress. Returns chapters inserted.

    Existing chapters are matched on either stored id or url, because the
    exporter writes `url or source_chapter_id` and the two differ for some
    sources. Matching on one alone would duplicate every chapter on a
    round trip.
    """
    existing = {}
    for chapter in db.get_chapters(manga_id):
        existing[chapter.source_chapter_id] = chapter
        if chapter.url:
            existing.setdefault(chapter.url, chapter)

    to_insert: List[Chapter] = []
    to_overwrite: List[Chapter] = []
    progress = {}
    for entry in restored.chapters:
        key = entry["url"]
        if not key:
            continue
        read, page = bool(entry["read"]), int(entry["last_page_read"] or 0)
        local = existing.get(key)
        if local is None:
            to_insert.append(Chapter(
                manga_id=manga_id,
                source_chapter_id=key,
                title=entry["name"],
                chapter_number=entry["chapter_number"],
                scanlator=entry["scanlator"],
                uploaded_at=(entry["date_upload"] / 1000.0) if entry["date_upload"] else None,
                source_order=entry["source_order"],
                read=read,
                last_page_read=page,
                url=key,
            ))
            continue
        if mode is ConflictMode.OVERWRITE:
            local.title = entry["name"] or local.title
            local.chapter_number = entry["chapter_number"]
            local.scanlator = entry["scanlator"]
            if entry["date_upload"]:
                local.uploaded_at = entry["date_upload"] / 1000.0
            local.source_order = entry["source_order"]
            to_overwrite.append(local)
            progress[local.source_chapter_id] = (read, page)
        else:
            progress[local.source_chapter_id] = (
                local.read or read,
                max(local.last_page_read or 0, page),
            )

    if to_insert or to_overwrite:
        db.upsert_chapters(to_insert + to_overwrite)
    db.restore_chapter_progress(manga_id, progress)
    # Inserting chapters does not refresh the cached count, and an all-new
    # chapter list leaves `progress` empty, so recompute unconditionally.
    db.update_unread_count(manga_id)
    return len(to_insert)


def _restore_history(db, manga_id: int, restored: RestoredManga) -> None:
    if not restored.history:
        return
    by_url = {}
    for chapter in db.get_chapters(manga_id):
        by_url[chapter.source_chapter_id] = chapter
        if chapter.url:
            by_url.setdefault(chapter.url, chapter)
    for entry in restored.history:
        chapter = by_url.get(entry["url"])
        if chapter is None or not entry["last_read"]:
            continue
        db.restore_history_entry(
            manga_id, chapter.id, chapter.last_page_read or 0, entry["last_read"] / 1000.0
        )


def _restore_tracking(db, manga_id: int, restored: RestoredManga, mode: ConflictMode):
    """
    Restore tracker links. Returns (restored, skipped as unsupported).

    Merge adds links the manga does not have yet; overwrite also replaces
    existing ones with the backup's state. Nothing is sent to the trackers:
    the next sync or pull reconciles with the remote list.
    """
    existing = {row["provider"] for row in db.get_manga_tracking(manga_id)}
    restored_count = skipped = 0
    for record in restored.tracking:
        entry = tracking_from_backup(record)
        if entry is None:
            skipped += 1
            continue
        if entry.provider in existing and mode is ConflictMode.MERGE:
            continue
        db.upsert_manga_tracking(
            manga_id=manga_id,
            provider=entry.provider,
            status=entry.status,
            progress=entry.progress,
            score=entry.score,
            url=entry.url,
            remote_id=entry.remote_id,
            library_id=entry.library_id,
            title=entry.title,
            total_chapters=entry.total_chapters,
            started_at=entry.started_at,
            finished_at=entry.finished_at,
        )
        restored_count += 1
    return restored_count, skipped


def _restore_reading_mode(db, manga_id: int, restored: RestoredManga, mode: ConflictMode):
    reading_mode = reading_mode_from_viewer_flags(restored.viewer_flags)
    if not reading_mode:
        return
    if mode is ConflictMode.MERGE and db.get_manga_reading_mode(manga_id):
        return
    db.set_manga_reading_mode(manga_id, reading_mode)


def import_tachibk(
    path: Path,
    *,
    apply: bool = False,
    add_to_default_category: bool = True,
    mode: ConflictMode = ConflictMode.MERGE,
    progress: Optional[Callable[[int, int], None]] = None,
) -> ImportResult:
    """
    Parse a .tachibk file and (optionally) write it into the DB.

    ``progress(done, total)`` is called after each manga, from the calling
    thread, so a UI caller must marshal it onto the main loop itself.
    """
    try:
        backup = parse_backup(path)
    except BackupError as exc:
        return ImportResult(backup=None, errors=[str(exc)])
    except Exception as exc:
        logger.exception("Failed to parse backup %s", path)
        return ImportResult(backup=None, errors=[f"Failed to parse backup: {exc}"])

    result = ImportResult(backup=backup, applied=False)
    if not apply or not backup.mangas:
        return result

    db = get_db()

    category_id_by_order: dict[int, int] = {}
    existing_categories = {c.name.lower(): c.id for c in db.get_categories()}
    for name, order in backup.categories:
        if not name:
            continue
        key = name.lower()
        if key in existing_categories:
            category_id_by_order[order] = existing_categories[key]
            continue
        category_id_by_order[order] = db.create_category(name)
        existing_categories[key] = category_id_by_order[order]
        result.imported_categories += 1

    default_category_id: Optional[int] = None
    if add_to_default_category:
        existing_categories = {c.name.lower(): c.id for c in db.get_categories()}
        target = "Imported"
        if target.lower() in existing_categories:
            default_category_id = existing_categories[target.lower()]
        else:
            default_category_id = db.create_category(target)
            result.imported_categories += 1

    total = len(backup.mangas)
    for done, restored in enumerate(backup.mangas, start=1):
        try:
            manga = _manga_to_library(restored)
            before = db.get_manga_by_source(manga.source_id, manga.source_manga_id)
            if before is None or mode is ConflictMode.OVERWRITE:
                db.upsert_manga(manga)
            row = db.get_manga_by_source(manga.source_id, manga.source_manga_id)
            if row is None:
                continue
            if before is None:
                result.new_manga += 1
            elif restored.favorite and not before.in_library:
                # The upsert never touches in_library on conflict, so a manga
                # that was only browsed before would stay out of the library.
                db.add_to_library(row.id)

            if default_category_id is not None:
                db.add_manga_to_category_bulk([row.id], default_category_id)
            for category_index in restored.categories:
                category_id = category_id_by_order.get(category_index)
                if category_id is not None:
                    db.add_manga_to_category_bulk([row.id], category_id)

            result.imported_chapters += _restore_chapters(db, row.id, restored, mode)
            _restore_history(db, row.id, restored)
            linked, skipped = _restore_tracking(db, row.id, restored, mode)
            result.imported_trackers += linked
            result.skipped_trackers += skipped
            _restore_reading_mode(db, row.id, restored, mode)
            result.imported_manga += 1
        except Exception as exc:
            logger.exception("Restoring %r failed", restored.title)
            result.errors.append(f"Restore failed for {restored.title!r}: {exc}")
        if progress is not None:
            progress(done, total)

    result.applied = True
    return result


__all__ = [
    "BackupError",
    "ConflictMode",
    "ImportPreview",
    "ImportResult",
    "RestoredBackup",
    "RestoredManga",
    "import_tachibk",
    "parse_backup",
    "preview_backup",
]
