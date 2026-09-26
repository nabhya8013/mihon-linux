"""
Local source: read manga from a folder on disk.

Android Mihon reads CBZ/ZIP archives and loose image folders out of a
designated directory, so a user's own scans sit alongside online sources.
This is the same idea for the desktop.

Expected layout, matching upstream:

    <local library>/
      Series Name/
        Chapter 1.cbz
        Chapter 2.cbz
        cover.jpg            <- optional; otherwise the first page is used
      Another Series/
        Volume 01/           <- a folder of loose images works too
          001.jpg
          002.jpg

CBZ and ZIP are the same container, so both are read with :mod:`zipfile`.
CBR/RAR is not supported: it needs a non-standard-library unrar
implementation, and the format is not redistributable.
"""
from __future__ import annotations

import json
import logging
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from ..core.database import DATA_DIR
from ..core.models import Chapter, ExtensionInfo, Manga, Page, SearchFilter
from .base import Extension

logger = logging.getLogger("local_source")

SOURCE_ID = "local"
SETTING_DIR = "local_source_dir"

DEFAULT_LOCAL_DIR = Path.home() / "Manga"
# Where extracted archive pages are staged for the reader, which needs real
# files on disk rather than bytes in memory.
EXTRACT_DIR = DATA_DIR / "local-pages"

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp")
ARCHIVE_SUFFIXES = (".cbz", ".zip")
COVER_NAMES = ("cover", "folder", "poster", "thumbnail")

# Metadata a user can drop next to a series to override what is inferred.
DETAILS_FILENAME = "details.json"

_CHAPTER_NUMBER_RE = re.compile(
    r"(?:^|[^\d.])(?:c(?:h(?:apter)?)?)?\s*[-_. ]?(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_chapter_number(name: str) -> float:
    """
    Best-effort chapter number from a filename.

    Returns -1.0 when nothing numeric is present, which is exactly the case
    source order exists for.
    """
    stem = Path(name).stem
    # Prefer an explicit "Chapter 12" / "Ch. 12" / "c012" marker.
    explicit = re.search(r"c(?:h(?:apter)?)?[\s._-]*(\d+(?:\.\d+)?)", stem, re.IGNORECASE)
    if explicit:
        return float(explicit.group(1))

    numbers = re.findall(r"\d+(?:\.\d+)?", stem)
    if not numbers:
        return -1.0
    # The last number in a name like "Series 03 - 014" is the chapter.
    return float(numbers[-1])


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def is_archive(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_SUFFIXES


def natural_key(name: str):
    """
    Sort key that orders "2.jpg" before "10.jpg".

    Plain string sorting puts "10" first, which scrambles page order in every
    archive that does not zero-pad.
    """
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", name)
    ]


@dataclass
class LocalChapter:
    """One chapter on disk: an archive file, or a folder of images."""

    path: Path
    name: str
    is_archive: bool


class LocalSource(Extension):
    """A source backed by a directory of archives and image folders."""

    def __init__(self, db=None, root: Optional[Path] = None):
        self._db = db
        self._root_override = Path(root) if root else None

    @property
    def info(self) -> ExtensionInfo:
        return ExtensionInfo(
            id=SOURCE_ID,
            name="Local",
            version="1.0.0",
            language="all",
            description=f"Manga read from {self.root}",
            installed=True,
        )

    # ── Configuration ─────────────────────────────────────────────────────

    @property
    def root(self) -> Path:
        """The configured library folder."""
        if self._root_override is not None:
            return self._root_override
        if self._db is not None:
            configured = (self._db.get_setting(SETTING_DIR, "") or "").strip()
            if configured:
                return Path(configured).expanduser()
        return DEFAULT_LOCAL_DIR

    def set_root(self, path) -> bool:
        """Point the source at a different folder. Returns whether it exists."""
        path = Path(path).expanduser()
        if self._db is not None:
            self._db.set_setting(SETTING_DIR, str(path))
        self._root_override = None
        return path.is_dir()

    # ── Browsing ──────────────────────────────────────────────────────────

    def get_popular(self, page: int = 1) -> Tuple[List[Manga], bool]:
        """Every series, alphabetically. A local library needs no ranking."""
        return self._listing(sort_key=lambda m: (m.title or "").lower())

    def get_latest(self, page: int = 1) -> Tuple[List[Manga], bool]:
        """Series by folder modification time, newest first."""
        return self._listing(
            sort_key=lambda m: -(self._series_mtime(m.source_manga_id))
        )

    def search(self, filters: SearchFilter, page: int = 1) -> Tuple[List[Manga], bool]:
        query = (filters.query or "").strip().lower()
        manga, _ = self._listing(sort_key=lambda m: (m.title or "").lower())
        if not query:
            return manga, False
        return [m for m in manga if query in (m.title or "").lower()], False

    def _listing(self, sort_key) -> Tuple[List[Manga], bool]:
        root = self.root
        if not root.is_dir():
            logger.info("local library folder does not exist: %s", root)
            return [], False

        manga = []
        for entry in sorted(root.iterdir(), key=lambda p: natural_key(p.name)):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            manga.append(self._series_to_manga(entry))

        manga.sort(key=sort_key)
        # A local library is read in one pass; there is nothing to paginate.
        return manga, False

    # ── Details ───────────────────────────────────────────────────────────

    def get_manga_details(self, manga: Manga) -> Manga:
        series = self._series_dir(manga.source_manga_id)
        if series is None:
            return manga

        updated = self._series_to_manga(series)
        updated.id = manga.id
        updated.in_library = manga.in_library
        updated.reading_status = manga.reading_status
        updated.added_at = manga.added_at
        updated.initialized = True
        return updated

    def get_chapters(self, manga: Manga) -> List[Chapter]:
        series = self._series_dir(manga.source_manga_id)
        if series is None:
            return []

        found = self._scan_chapters(series)
        # Newest first, matching what an online source returns.
        found.sort(key=lambda c: natural_key(c.name), reverse=True)

        chapters = []
        for order, local in enumerate(found):
            chapter = Chapter()
            chapter.manga_id = manga.id or 0
            # Relative to the library root so the id survives a library move.
            chapter.source_chapter_id = str(local.path.relative_to(self.root))
            chapter.url = chapter.source_chapter_id
            chapter.title = local.name
            chapter.chapter_number = parse_chapter_number(local.name)
            chapter.source_order = order
            try:
                chapter.uploaded_at = local.path.stat().st_mtime
            except OSError:
                chapter.uploaded_at = None
            chapters.append(chapter)
        return chapters

    def get_pages(self, chapter: Chapter) -> List[Page]:
        target = self.root / (chapter.source_chapter_id or chapter.url)
        if not target.exists():
            logger.warning("local chapter is missing: %s", target)
            return []

        if target.is_dir():
            files = sorted(
                (f for f in target.iterdir() if f.is_file() and is_image(f)),
                key=lambda f: natural_key(f.name),
            )
            return [
                Page(index=i, url=str(f), image_url=str(f), local_path=str(f))
                for i, f in enumerate(files)
            ]

        return self._extract_archive(target)

    # ── Archives ──────────────────────────────────────────────────────────

    def _extract_archive(self, archive: Path) -> List[Page]:
        """
        Unpack an archive's images into a staging folder.

        The reader loads pages from real files, so the images are written out
        rather than held in memory. Extraction is skipped when the staging
        folder already holds them.
        """
        target_dir = EXTRACT_DIR / _stable_name(archive)

        try:
            with zipfile.ZipFile(archive) as bundle:
                names = sorted(
                    (
                        n for n in bundle.namelist()
                        if not n.endswith("/") and is_image(Path(n))
                        # Skip macOS resource forks, which are not real pages.
                        and not Path(n).name.startswith("._")
                    ),
                    key=natural_key,
                )
                if not names:
                    logger.warning("no images inside %s", archive)
                    return []

                target_dir.mkdir(parents=True, exist_ok=True)
                pages = []
                for index, name in enumerate(names):
                    # Flatten to a numbered file: archive paths can contain
                    # directories, and one of them escaping the staging folder
                    # would be a path-traversal write.
                    suffix = Path(name).suffix.lower()
                    out = target_dir / f"{index:04d}{suffix}"
                    if not out.exists() or out.stat().st_size == 0:
                        with bundle.open(name) as src, out.open("wb") as dst:
                            dst.write(src.read())
                    pages.append(Page(
                        index=index, url=str(out), image_url=str(out),
                        local_path=str(out),
                    ))
                return pages
        except (zipfile.BadZipFile, OSError) as exc:
            logger.error("could not read %s: %s", archive, exc)
            return []

    # ── Internals ─────────────────────────────────────────────────────────

    def _series_dir(self, source_manga_id: str) -> Optional[Path]:
        if not source_manga_id:
            return None
        candidate = self.root / source_manga_id
        return candidate if candidate.is_dir() else None

    def _series_mtime(self, source_manga_id: str) -> float:
        series = self._series_dir(source_manga_id)
        if series is None:
            return 0.0
        try:
            return series.stat().st_mtime
        except OSError:
            return 0.0

    def _scan_chapters(self, series: Path) -> List[LocalChapter]:
        found = []
        try:
            entries = list(series.iterdir())
        except OSError as exc:
            logger.error("could not read %s: %s", series, exc)
            return []

        loose_images = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_file() and is_archive(entry):
                found.append(LocalChapter(entry, entry.stem, True))
            elif entry.is_dir():
                found.append(LocalChapter(entry, entry.name, False))
            elif entry.is_file() and is_image(entry) and entry.stem.lower() not in COVER_NAMES:
                loose_images.append(entry)

        # A series folder holding images directly is one single chapter.
        if not found and loose_images:
            found.append(LocalChapter(series, series.name, False))
        return found

    def _series_to_manga(self, series: Path) -> Manga:
        manga = Manga(
            source_id=SOURCE_ID,
            source_manga_id=series.name,
            title=series.name,
            url=series.name,
            status="",
            initialized=True,
        )

        cover = self._find_cover(series)
        if cover is not None:
            manga.cover_url = str(cover)
            manga.cover_local_path = str(cover)

        self._apply_details_file(series, manga)
        return manga

    def _find_cover(self, series: Path) -> Optional[Path]:
        try:
            entries = list(series.iterdir())
        except OSError:
            return None

        for entry in entries:
            if entry.is_file() and is_image(entry) and entry.stem.lower() in COVER_NAMES:
                return entry

        # No named cover, so fall back to the first image of the first chapter.
        for entry in sorted(entries, key=lambda p: natural_key(p.name)):
            if entry.is_dir():
                images = sorted(
                    (f for f in entry.iterdir() if f.is_file() and is_image(f)),
                    key=lambda f: natural_key(f.name),
                )
                if images:
                    return images[0]
        return None

    @staticmethod
    def _apply_details_file(series: Path, manga: Manga):
        """Apply a user-written details.json, if the series has one."""
        details = series / DETAILS_FILENAME
        if not details.is_file():
            return
        try:
            data = json.loads(details.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("could not read %s: %s", details, exc)
            return

        manga.title = str(data.get("title") or manga.title)
        manga.author = str(data.get("author") or "")
        manga.artist = str(data.get("artist") or "")
        manga.description = str(data.get("description") or "")
        manga.status = str(data.get("status") or "")
        genres = data.get("genre") or data.get("genres") or []
        if isinstance(genres, str):
            genres = [g.strip() for g in genres.split(",") if g.strip()]
        if isinstance(genres, list):
            manga.genres = [str(g) for g in genres]


def _stable_name(path: Path) -> str:
    """A filesystem-safe staging folder name derived from an archive path."""
    import hashlib
    digest = hashlib.md5(str(path).encode("utf-8")).hexdigest()[:16]
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", path.stem)[:48]
    return f"{safe}-{digest}"


__all__ = [
    "ARCHIVE_SUFFIXES",
    "DEFAULT_LOCAL_DIR",
    "EXTRACT_DIR",
    "IMAGE_SUFFIXES",
    "LocalSource",
    "SETTING_DIR",
    "SOURCE_ID",
    "is_archive",
    "is_image",
    "natural_key",
    "parse_chapter_number",
]
