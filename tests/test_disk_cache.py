"""Tests for the split on-disk image cache."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mihon.core import disk_cache


class DiskCacheTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._covers = root / "covers"
        self._pages = root / "page-cache"
        self._covers.mkdir()
        self._pages.mkdir()
        self._patches = [
            patch.object(disk_cache, "COVERS_DIR", self._covers),
            patch.object(disk_cache, "PAGES_DIR", self._pages),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    # ── Routing ───────────────────────────────────────────────────────────

    def test_covers_and_pages_use_separate_directories(self):
        cover = disk_cache.cache_path("http://x/1.jpg", disk_cache.KIND_COVER)
        page = disk_cache.cache_path("http://x/1.jpg", disk_cache.KIND_PAGE)
        self.assertEqual(cover.parent, self._covers)
        self.assertEqual(page.parent, self._pages)
        self.assertNotEqual(cover, page)

    def test_the_same_url_hashes_to_the_same_name(self):
        a = disk_cache.cache_path("http://x/1.jpg")
        b = disk_cache.cache_path("http://x/1.jpg")
        self.assertEqual(a, b)

    def test_different_urls_hash_differently(self):
        a = disk_cache.cache_path("http://x/1.jpg")
        b = disk_cache.cache_path("http://x/2.jpg")
        self.assertNotEqual(a, b)

    def test_page_is_the_default_kind(self):
        self.assertEqual(
            disk_cache.cache_path("http://x/1.jpg").parent, self._pages
        )

    # ── Read and write ────────────────────────────────────────────────────

    def test_write_then_read_round_trip(self):
        disk_cache.write("http://x/1.jpg", b"payload")
        self.assertEqual(disk_cache.read("http://x/1.jpg"), b"payload")

    def test_reading_a_missing_url_returns_none(self):
        self.assertIsNone(disk_cache.read("http://x/never.jpg"))

    def test_a_cover_write_is_not_visible_as_a_page(self):
        disk_cache.write("http://x/1.jpg", b"cover", disk_cache.KIND_COVER)
        self.assertIsNone(disk_cache.read("http://x/1.jpg", disk_cache.KIND_PAGE))

    def test_write_creates_a_missing_directory(self):
        import shutil
        shutil.rmtree(self._pages)
        self.assertIsNotNone(disk_cache.write("http://x/1.jpg", b"data"))

    def test_reading_refreshes_the_access_time(self):
        disk_cache.write("http://x/1.jpg", b"data")
        path = disk_cache.cache_path("http://x/1.jpg")
        os.utime(path, (0, 0))
        disk_cache.read("http://x/1.jpg")
        self.assertGreater(path.stat().st_mtime, 0)

    # ── Size and pruning ──────────────────────────────────────────────────

    def test_cache_size_sums_the_files(self):
        disk_cache.write("a", b"x" * 100)
        disk_cache.write("b", b"x" * 50)
        self.assertEqual(disk_cache.cache_size(), 150)

    def test_size_is_reported_per_kind(self):
        disk_cache.write("a", b"x" * 100, disk_cache.KIND_PAGE)
        disk_cache.write("b", b"x" * 10, disk_cache.KIND_COVER)
        self.assertEqual(disk_cache.cache_size(disk_cache.KIND_PAGE), 100)
        self.assertEqual(disk_cache.cache_size(disk_cache.KIND_COVER), 10)

    def test_prune_is_a_no_op_under_the_limit(self):
        disk_cache.write("a", b"x" * 100)
        self.assertEqual(disk_cache.prune(max_bytes=1000), 0)
        self.assertEqual(disk_cache.cache_size(), 100)

    def test_prune_evicts_oldest_first(self):
        for name, age in [("old", 0), ("mid", 1000), ("new", 2000)]:
            disk_cache.write(name, b"x" * 100)
            os.utime(disk_cache.cache_path(name), (age, age))

        disk_cache.prune(max_bytes=250)
        self.assertIsNone(disk_cache.read("old"))
        self.assertIsNotNone(disk_cache.read("new"))

    def test_prune_stops_once_it_fits(self):
        for name, age in [("a", 0), ("b", 100), ("c", 200)]:
            disk_cache.write(name, b"x" * 100)
            os.utime(disk_cache.cache_path(name), (age, age))
        freed = disk_cache.prune(max_bytes=250)
        self.assertEqual(freed, 100)
        self.assertEqual(disk_cache.cache_size(), 200)

    def test_prune_leaves_covers_alone_by_default(self):
        disk_cache.write("cover", b"x" * 1000, disk_cache.KIND_COVER)
        disk_cache.write("page", b"x" * 1000, disk_cache.KIND_PAGE)
        disk_cache.prune(max_bytes=0)
        self.assertIsNotNone(disk_cache.read("cover", disk_cache.KIND_COVER))
        self.assertIsNone(disk_cache.read("page", disk_cache.KIND_PAGE))

    def test_prune_on_a_missing_directory_is_harmless(self):
        import shutil
        shutil.rmtree(self._pages)
        self.assertEqual(disk_cache.prune(max_bytes=0), 0)

    # ── Clearing ──────────────────────────────────────────────────────────

    def test_clear_removes_everything_of_one_kind(self):
        disk_cache.write("a", b"x" * 100)
        disk_cache.write("b", b"x" * 100)
        disk_cache.write("cover", b"x" * 50, disk_cache.KIND_COVER)
        freed = disk_cache.clear(disk_cache.KIND_PAGE)
        self.assertEqual(freed, 200)
        self.assertEqual(disk_cache.cache_size(disk_cache.KIND_PAGE), 0)
        self.assertEqual(disk_cache.cache_size(disk_cache.KIND_COVER), 50)

    def test_clearing_an_empty_cache_frees_nothing(self):
        self.assertEqual(disk_cache.clear(), 0)


if __name__ == "__main__":
    unittest.main()
