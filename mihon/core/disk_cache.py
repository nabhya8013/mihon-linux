"""
On-disk image cache.

Every image the app fetched — library covers and manga pages alike — used to
land in one directory keyed by a URL hash, with nothing ever removing it. A
few chapters of a long series runs to gigabytes that never come back.

This module splits the two apart, because they have opposite lifetimes:

covers
    Small, few, and wanted for as long as the manga is in the library. Kept
    until the cache is cleared by hand.

pages
    Large, many, and worth keeping only while the user is likely to reopen
    the chapter. Bounded by total size and pruned least-recently-used first.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Optional

from .database import COVERS_DIR, DATA_DIR

logger = logging.getLogger("disk_cache")

PAGES_DIR = DATA_DIR / "page-cache"

# Total bytes of cached page images to keep. Roughly a few hundred chapters.
DEFAULT_PAGE_CACHE_BYTES = 512 * 1024 * 1024

KIND_COVER = "cover"
KIND_PAGE = "page"


def ensure_dirs():
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)


def _hashed_name(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def cache_dir_for(kind: str) -> Path:
    return COVERS_DIR if kind == KIND_COVER else PAGES_DIR


def cache_path(url: str, kind: str = KIND_PAGE) -> Path:
    """Where a URL's bytes live on disk, by cache kind."""
    return cache_dir_for(kind) / _hashed_name(url)


def read(url: str, kind: str = KIND_PAGE) -> Optional[bytes]:
    """
    Cached bytes for a URL, or None.

    Reading refreshes the file's access time so the LRU prune keeps what is
    actually being used.
    """
    path = cache_path(url, kind)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    _touch(path)
    return data


def write(url: str, data: bytes, kind: str = KIND_PAGE) -> Optional[Path]:
    """Store bytes for a URL. Returns the path, or None when it could not."""
    path = cache_path(url, kind)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
    except OSError as exc:
        logger.warning("could not cache %s: %s", url, exc)
        return None


def _touch(path: Path):
    try:
        now = time.time()
        os.utime(path, (now, now))
    except OSError:
        pass


def cache_size(kind: str = KIND_PAGE) -> int:
    """Total bytes held by one cache kind."""
    total = 0
    directory = cache_dir_for(kind)
    if not directory.exists():
        return 0
    for entry in directory.iterdir():
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def prune(max_bytes: int = DEFAULT_PAGE_CACHE_BYTES, kind: str = KIND_PAGE) -> int:
    """
    Delete least-recently-used files until the cache fits ``max_bytes``.

    Returns the number of bytes freed. Covers are never pruned by default —
    pass ``kind=KIND_COVER`` deliberately if that is what you want.
    """
    directory = cache_dir_for(kind)
    if not directory.exists():
        return 0

    entries = []
    total = 0
    for entry in directory.iterdir():
        try:
            if not entry.is_file():
                continue
            stat = entry.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, entry))
        total += stat.st_size

    if total <= max_bytes:
        return 0

    entries.sort(key=lambda item: item[0])  # oldest first
    freed = 0
    for _mtime, size, path in entries:
        if total - freed <= max_bytes:
            break
        try:
            path.unlink()
            freed += size
        except OSError:
            continue

    if freed:
        logger.info("pruned %d bytes from the %s cache", freed, kind)
    return freed


def clear(kind: str = KIND_PAGE) -> int:
    """Delete everything in one cache kind. Returns bytes freed."""
    directory = cache_dir_for(kind)
    if not directory.exists():
        return 0
    freed = 0
    for entry in directory.iterdir():
        try:
            if not entry.is_file():
                continue
            size = entry.stat().st_size
            entry.unlink()
            freed += size
        except OSError:
            continue
    return freed


def migrate_legacy_page_files() -> int:
    """
    One-time cleanup for installs that cached pages into ``covers/``.

    There is no way to tell a page from a cover after the fact — both are
    just hashed filenames — so this only reports how many files are there.
    Pruning covers is left to the user through Settings.
    """
    if not COVERS_DIR.exists():
        return 0
    return sum(1 for entry in COVERS_DIR.iterdir() if entry.is_file())


__all__ = [
    "DEFAULT_PAGE_CACHE_BYTES",
    "KIND_COVER",
    "KIND_PAGE",
    "PAGES_DIR",
    "cache_path",
    "cache_size",
    "clear",
    "ensure_dirs",
    "prune",
    "read",
    "write",
]
