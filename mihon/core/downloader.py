"""
Download manager for Mihon Linux.
Queue-based, threaded chapter downloader with progress tracking.
"""
import os
import threading
import time
from urllib.parse import urlparse
from pathlib import Path
from typing import Dict, List, Optional, Callable
from .database import get_db, DOWNLOADS_DIR
from .http_client import create_http_session
from .models import Manga, Chapter, Page, DownloadStatus, DownloadItem
import logging

logger = logging.getLogger("downloader")

_REFERER_MAP = {
    "mangadex.org": "https://mangadex.org",
    "uploads.mangadex.org": "https://mangadex.org",
    "mangadex.network": "https://mangadex.org",
    "allmanga.to": "https://allmanga.to",
    "allanime.day": "https://allmanga.to",
    "aln.youtube-anime.com": "https://allmanga.to",
}


def _get_referer(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
        for domain, referer in _REFERER_MAP.items():
            if host == domain or host.endswith("." + domain):
                return referer
    except Exception:
        pass
    return ""


class DownloadManager:
    """
    Manages chapter downloads in background threads.
    Emits callbacks on progress and status changes.
    """

    DEFAULT_MAX_WORKERS = 2

    def __init__(self):
        # Pending chapter ids in dispatch order; a worker pops from the front.
        # Reordering (move_up/move_down/prioritize) only touches this list,
        # so it's plain and index-addressable rather than a queue.Queue.
        self._pending: List[int] = []
        self._pending_pages: Dict[int, List[Page]] = {}
        self._active: Dict[int, DownloadItem] = {}   # chapter_id -> item
        self._lock = threading.Condition()
        self._workers: List[threading.Thread] = []
        self._running = True
        self._on_progress_cb: Optional[Callable] = None
        self._on_status_cb: Optional[Callable] = None
        self._session = create_http_session()
        try:
            self.MAX_WORKERS = int(get_db().get_setting(
                "max_simultaneous_downloads", str(self.DEFAULT_MAX_WORKERS)
            ))
        except ValueError:
            self.MAX_WORKERS = self.DEFAULT_MAX_WORKERS
        self._start_workers()

    def _start_workers(self):
        for _ in range(self.MAX_WORKERS):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._workers.append(t)

    def on_progress(self, cb: Callable):
        """Register callback(chapter_id, pages_done, total_pages)."""
        self._on_progress_cb = cb

    def on_status(self, cb: Callable):
        """Register callback(chapter_id, DownloadStatus)."""
        self._on_status_cb = cb

    def enqueue(self, manga: Manga, chapter: Chapter, pages: List[Page]) -> DownloadItem:
        """Add a chapter to the download queue."""
        item = DownloadItem(
            manga=manga,
            chapter=chapter,
            status=DownloadStatus.QUEUED,
            total_pages=len(pages),
        )
        with self._lock:
            self._active[chapter.id] = item
            self._pending_pages[chapter.id] = pages
            self._pending.append(chapter.id)
            self._lock.notify()
        get_db().update_download_status(chapter.id, DownloadStatus.QUEUED)
        if self._on_status_cb:
            self._on_status_cb(chapter.id, DownloadStatus.QUEUED)
        return item

    def cancel(self, chapter_id: int):
        with self._lock:
            if chapter_id in self._active:
                self._active[chapter_id].status = DownloadStatus.ERROR
                self._active[chapter_id].error_message = "Cancelled"

    def remove(self, chapter_id: int):
        """Drop a finished, failed, or cancelled item from the visible queue."""
        with self._lock:
            self._active.pop(chapter_id, None)

    def retry(self, chapter_id: int):
        """Re-fetch pages for a failed/cancelled item and re-enqueue it."""
        with self._lock:
            item = self._active.get(chapter_id)
        if not item:
            return

        def fetch_and_requeue():
            try:
                from ..extensions.registry import get_registry
                ext = get_registry().get(item.manga.source_id)
                if not ext:
                    return
                pages = ext.get_pages(item.chapter)
                self.enqueue(item.manga, item.chapter, pages)
            except Exception as e:
                logger.error("retry error for chapter %s: %s", chapter_id, e)

        threading.Thread(target=fetch_and_requeue, daemon=True).start()

    def get_item(self, chapter_id: int) -> Optional[DownloadItem]:
        with self._lock:
            return self._active.get(chapter_id)

    def get_queue(self) -> List[DownloadItem]:
        with self._lock:
            return list(self._active.values())

    def move_to_front(self, chapter_id: int) -> bool:
        """Prioritize a still-pending (not yet downloading) chapter."""
        with self._lock:
            if chapter_id not in self._pending or self._pending[0] == chapter_id:
                return False
            self._pending.remove(chapter_id)
            self._pending.insert(0, chapter_id)
            return True

    def move_up(self, chapter_id: int) -> bool:
        return self._shift(chapter_id, -1)

    def move_down(self, chapter_id: int) -> bool:
        return self._shift(chapter_id, 1)

    def _shift(self, chapter_id: int, delta: int) -> bool:
        with self._lock:
            try:
                idx = self._pending.index(chapter_id)
            except ValueError:
                return False
            new_idx = idx + delta
            if not (0 <= new_idx < len(self._pending)):
                return False
            self._pending[idx], self._pending[new_idx] = (
                self._pending[new_idx], self._pending[idx],
            )
            return True

    def pending_order(self) -> List[int]:
        """Chapter ids not yet started, front (next) to back."""
        with self._lock:
            return list(self._pending)

    def _worker(self):
        while True:
            with self._lock:
                while self._running and not self._pending:
                    self._lock.wait(timeout=1)
                if not self._running:
                    return
                if not self._pending:
                    continue
                chapter_id = self._pending.pop(0)
                item = self._active.get(chapter_id)
                pages = self._pending_pages.pop(chapter_id, None)

            if item is None or pages is None:
                continue
            self._download_chapter(item, pages)

    def _download_chapter(self, item: DownloadItem, pages: List[Page]):
        chapter = item.chapter
        manga = item.manga

        with self._lock:
            if item.status == DownloadStatus.ERROR:  # was cancelled
                return

        item.status = DownloadStatus.DOWNLOADING
        get_db().update_download_status(chapter.id, DownloadStatus.DOWNLOADING)
        if self._on_status_cb:
            self._on_status_cb(chapter.id, DownloadStatus.DOWNLOADING)

        # Build local directory: <download_dir>/source/manga_title/Ch.XXX/
        downloads_root = Path(get_db().get_setting("download_dir", str(DOWNLOADS_DIR)))
        safe_title = self._safe_name(manga.title)
        ch_num = f"Ch.{chapter.chapter_number:g}"
        chapter_dir = downloads_root / item.manga.source_id / safe_title / ch_num
        chapter_dir.mkdir(parents=True, exist_ok=True)

        downloaded = 0
        success_count = 0
        try:
            for page in pages:
                with self._lock:
                    if item.status == DownloadStatus.ERROR:
                        return  # cancelled

                url = page.image_url or page.url
                if not url:
                    downloaded += 1
                    continue

                ext = self._guess_extension(url)
                filename = f"{page.index:04d}{ext}"
                dest = chapter_dir / filename

                if dest.exists():
                    downloaded += 1
                    success_count += 1
                    item.pages_downloaded = downloaded
                    item.progress = downloaded / max(len(pages), 1)
                    if self._on_progress_cb:
                        self._on_progress_cb(chapter.id, downloaded, len(pages))
                    continue

                try:
                    headers = {}
                    referer = _get_referer(url)
                    if referer:
                        headers["Referer"] = referer
                    resp = self._session.get(url, timeout=20, stream=True, headers=headers)
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    downloaded += 1
                    success_count += 1
                    item.pages_downloaded = downloaded
                    item.progress = downloaded / max(len(pages), 1)
                    if self._on_progress_cb:
                        self._on_progress_cb(chapter.id, downloaded, len(pages))
                except Exception as e:
                    logger.warning("failed page %s: %s", page.index, e)
                    # Continue with remaining pages
                    downloaded += 1

            if success_count == len(pages):
                item.status = DownloadStatus.DOWNLOADED
                item.progress = 1.0
                local_path = str(chapter_dir)
                get_db().update_download_status(chapter.id, DownloadStatus.DOWNLOADED, local_path)
                if self._on_status_cb:
                    self._on_status_cb(chapter.id, DownloadStatus.DOWNLOADED)
            else:
                item.status = DownloadStatus.ERROR
                failed = len(pages) - success_count
                item.error_message = f"Failed to download {failed}/{len(pages)} pages"
                get_db().update_download_status(chapter.id, DownloadStatus.ERROR)
                if self._on_status_cb:
                    self._on_status_cb(chapter.id, DownloadStatus.ERROR)

        except Exception as e:
            item.status = DownloadStatus.ERROR
            item.error_message = str(e)
            get_db().update_download_status(chapter.id, DownloadStatus.ERROR)
            if self._on_status_cb:
                self._on_status_cb(chapter.id, DownloadStatus.ERROR)

    @staticmethod
    def _safe_name(name: str) -> str:
        """Make a string safe for use as a directory name."""
        return "".join(c if c.isalnum() or c in " ._-" else "_" for c in name).strip()

    @staticmethod
    def _guess_extension(url: str) -> str:
        """Guess image file extension from URL."""
        url_path = url.split("?")[0].split("#")[0]
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"):
            if url_path.lower().endswith(ext):
                return ext
        return ".jpg"

    def shutdown(self):
        with self._lock:
            self._running = False
            self._lock.notify_all()


# Singleton
_manager: Optional[DownloadManager] = None

def get_download_manager() -> DownloadManager:
    global _manager
    if _manager is None:
        _manager = DownloadManager()
    return _manager
