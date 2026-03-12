"""
Download manager for Mihon Linux.
Queue-based, threaded chapter downloader with progress tracking.
"""
import os
import threading
import queue
import time
import requests
from pathlib import Path
from typing import Dict, List, Optional, Callable
from .database import get_db, DOWNLOADS_DIR
from .models import Manga, Chapter, Page, DownloadStatus, DownloadItem


class DownloadManager:
    """
    Manages chapter downloads in background threads.
    Emits callbacks on progress and status changes.
    """

    MAX_WORKERS = 2

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._active: Dict[int, DownloadItem] = {}   # chapter_id -> item
        self._lock = threading.Lock()
        self._workers: List[threading.Thread] = []
        self._running = True
        self._on_progress_cb: Optional[Callable] = None
        self._on_status_cb: Optional[Callable] = None
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
        })
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
        get_db().update_download_status(chapter.id, DownloadStatus.QUEUED)
        self._queue.put((item, pages))
        if self._on_status_cb:
            self._on_status_cb(chapter.id, DownloadStatus.QUEUED)
        return item

    def cancel(self, chapter_id: int):
        with self._lock:
            if chapter_id in self._active:
                self._active[chapter_id].status = DownloadStatus.ERROR
                self._active[chapter_id].error_message = "Cancelled"

    def get_item(self, chapter_id: int) -> Optional[DownloadItem]:
        with self._lock:
            return self._active.get(chapter_id)

    def get_queue(self) -> List[DownloadItem]:
        with self._lock:
            return list(self._active.values())

    def _worker(self):
        while self._running:
            try:
                item, pages = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            self._download_chapter(item, pages)
            self._queue.task_done()

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

        # Build local directory: downloads/source/manga_title/Ch.XXX/
        safe_title = self._safe_name(manga.title)
        ch_num = f"Ch.{chapter.chapter_number:g}"
        chapter_dir = DOWNLOADS_DIR / item.manga.source_id / safe_title / ch_num
        chapter_dir.mkdir(parents=True, exist_ok=True)

        downloaded = 0
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
                    item.pages_downloaded = downloaded
                    item.progress = downloaded / max(len(pages), 1)
                    if self._on_progress_cb:
                        self._on_progress_cb(chapter.id, downloaded, len(pages))
                    continue

                try:
                    resp = self._session.get(url, timeout=20, stream=True)
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    downloaded += 1
                    item.pages_downloaded = downloaded
                    item.progress = downloaded / max(len(pages), 1)
                    if self._on_progress_cb:
                        self._on_progress_cb(chapter.id, downloaded, len(pages))
                except Exception as e:
                    print(f"[downloader] Failed page {page.index}: {e}")
                    # Continue with remaining pages
                    downloaded += 1

            item.status = DownloadStatus.DOWNLOADED
            item.progress = 1.0
            local_path = str(chapter_dir)
            get_db().update_download_status(chapter.id, DownloadStatus.DOWNLOADED, local_path)
            if self._on_status_cb:
                self._on_status_cb(chapter.id, DownloadStatus.DOWNLOADED)

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
        self._running = False


# Singleton
_manager: Optional[DownloadManager] = None

def get_download_manager() -> DownloadManager:
    global _manager
    if _manager is None:
        _manager = DownloadManager()
    return _manager
