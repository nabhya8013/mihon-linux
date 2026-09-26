"""
Tests for DownloadManager's pending-queue reordering and lifecycle.

DownloadManager reads/writes through the real database.get_db() singleton
(download_dir, max_simultaneous_downloads, per-chapter status), so each test
gets its own fresh sqlite file under a temp XDG_DATA_HOME - the same
isolation _fresh_db() uses in test_database_concurrency.py, extended one
level so downloader.py's already-imported `get_db`/`DOWNLOADS_DIR` rebind to
the fresh database module too.
"""
import importlib
import os
import tempfile
import time
import unittest


def _fresh_manager():
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    from mihon.core import database
    importlib.reload(database)
    from mihon.core import downloader
    importlib.reload(downloader)
    return downloader


class ReorderTests(unittest.TestCase):
    """
    Chapters are seeded straight into the pending list rather than through
    enqueue(), so reorder logic is exercised in isolation from the worker
    threads racing to drain it.
    """

    def setUp(self):
        self.downloader = _fresh_manager()
        self.dm = self.downloader.DownloadManager()
        self.manga = self.downloader.Manga(id=1, source_id="test", title="Reorder Test")

    def tearDown(self):
        self.dm.shutdown()

    def _seed(self, chapter_ids):
        with self.dm._lock:
            for cid in chapter_ids:
                ch = self.downloader.Chapter(id=cid, manga_id=1, chapter_number=float(cid))
                item = self.downloader.DownloadItem(
                    manga=self.manga, chapter=ch,
                    status=self.downloader.DownloadStatus.QUEUED, total_pages=0,
                )
                self.dm._active[cid] = item
                self.dm._pending_pages[cid] = []
                self.dm._pending.append(cid)

    def test_pending_order_reflects_seed_order(self):
        self._seed([1, 2, 3])
        self.assertEqual(self.dm.pending_order(), [1, 2, 3])

    def test_move_to_front(self):
        self._seed([1, 2, 3])
        self.assertTrue(self.dm.move_to_front(3))
        self.assertEqual(self.dm.pending_order(), [3, 1, 2])

    def test_move_to_front_already_at_front_is_a_noop(self):
        self._seed([1, 2, 3])
        self.assertFalse(self.dm.move_to_front(1))
        self.assertEqual(self.dm.pending_order(), [1, 2, 3])

    def test_move_to_front_of_an_unknown_chapter_returns_false(self):
        self._seed([1, 2, 3])
        self.assertFalse(self.dm.move_to_front(999))

    def test_move_up_and_down(self):
        self._seed([1, 2, 3])
        self.assertTrue(self.dm.move_up(2))
        self.assertEqual(self.dm.pending_order(), [2, 1, 3])
        self.assertTrue(self.dm.move_down(2))
        self.assertEqual(self.dm.pending_order(), [1, 2, 3])

    def test_move_up_at_the_front_returns_false(self):
        self._seed([1, 2, 3])
        self.assertFalse(self.dm.move_up(1))
        self.assertEqual(self.dm.pending_order(), [1, 2, 3])

    def test_move_down_at_the_back_returns_false(self):
        self._seed([1, 2, 3])
        self.assertFalse(self.dm.move_down(3))
        self.assertEqual(self.dm.pending_order(), [1, 2, 3])

    def test_reordering_an_unknown_chapter_returns_false(self):
        self._seed([1, 2, 3])
        self.assertFalse(self.dm.move_up(999))
        self.assertFalse(self.dm.move_down(999))


class LifecycleTests(unittest.TestCase):
    """
    Pages with no url are treated as already satisfied (see _download_chapter),
    so enqueuing with an empty page list exercises the full worker pipeline
    deterministically without a network call.
    """

    def setUp(self):
        self.downloader = _fresh_manager()
        self.dm = self.downloader.DownloadManager()
        self.manga = self.downloader.Manga(id=1, source_id="lifecycle", title="Lifecycle Test")

    def tearDown(self):
        self.dm.shutdown()

    def _wait_for(self, item, statuses, timeout=2.5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if item.status in statuses:
                return True
            time.sleep(0.02)
        return False

    def test_enqueue_with_no_pages_downloads_immediately(self):
        chapter = self.downloader.Chapter(id=1, manga_id=1, chapter_number=1.0)
        item = self.dm.enqueue(self.manga, chapter, [])
        self.assertTrue(self._wait_for(item, {self.downloader.DownloadStatus.DOWNLOADED}))

    def test_multiple_downloads_all_complete(self):
        items = [
            self.dm.enqueue(
                self.manga,
                self.downloader.Chapter(id=100 + i, manga_id=1, chapter_number=float(i)),
                [],
            )
            for i in range(5)
        ]
        for item in items:
            self.assertTrue(self._wait_for(item, {self.downloader.DownloadStatus.DOWNLOADED}))

    def test_remove_drops_a_finished_item_from_the_visible_queue(self):
        chapter = self.downloader.Chapter(id=2, manga_id=1, chapter_number=2.0)
        item = self.dm.enqueue(self.manga, chapter, [])
        self._wait_for(item, {self.downloader.DownloadStatus.DOWNLOADED})
        self.dm.remove(2)
        self.assertIsNone(self.dm.get_item(2))
        self.assertNotIn(2, [it.chapter.id for it in self.dm.get_queue()])

    def test_cancel_never_raises_and_reaches_a_terminal_status(self):
        chapter = self.downloader.Chapter(id=3, manga_id=1, chapter_number=3.0)
        item = self.dm.enqueue(self.manga, chapter, [])
        self.dm.cancel(3)  # may race a worker that already finished it - must not raise
        terminal = {self.downloader.DownloadStatus.DOWNLOADED, self.downloader.DownloadStatus.ERROR}
        self.assertTrue(self._wait_for(item, terminal))


if __name__ == "__main__":
    unittest.main()
