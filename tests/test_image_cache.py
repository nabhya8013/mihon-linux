"""Tests for the image loader's bounded LRU cache."""
import unittest

import gi
gi.require_version("GdkPixbuf", "2.0")

from mihon.core import image_loader


class FakePixbuf:
    def __init__(self, name):
        self.name = name


class ImageCacheTests(unittest.TestCase):

    def setUp(self):
        image_loader.clear_cache()
        self._original_limit = image_loader._cache_limit
        image_loader.set_cache_limit(3)

    def tearDown(self):
        image_loader.clear_cache()
        image_loader.set_cache_limit(self._original_limit)

    def _put(self, url):
        image_loader._cache_put(image_loader._cache_key(url, -1, -1), FakePixbuf(url))

    def test_entries_are_retrievable(self):
        self._put("a")
        self.assertTrue(image_loader.is_cached("a"))
        self.assertEqual(image_loader.cache_size(), 1)

    def test_cache_is_bounded(self):
        for url in "abcde":
            self._put(url)
        self.assertEqual(image_loader.cache_size(), 3)

    def test_least_recently_used_is_dropped_first(self):
        for url in "abc":
            self._put(url)
        self._put("d")
        self.assertFalse(image_loader.is_cached("a"))
        self.assertTrue(image_loader.is_cached("d"))

    def test_a_read_refreshes_recency(self):
        for url in "abc":
            self._put(url)
        image_loader._cache_get(image_loader._cache_key("a", -1, -1))
        self._put("d")
        # "a" was just read, so "b" is now the oldest.
        self.assertTrue(image_loader.is_cached("a"))
        self.assertFalse(image_loader.is_cached("b"))

    def test_lowering_the_limit_evicts_immediately(self):
        for url in "abc":
            self._put(url)
        image_loader.set_cache_limit(1)
        self.assertEqual(image_loader.cache_size(), 1)

    def test_limit_never_drops_below_one(self):
        image_loader.set_cache_limit(0)
        self.assertEqual(image_loader._cache_limit, 1)

    def test_evict_removes_one_entry(self):
        self._put("a")
        self._put("b")
        image_loader.evict("a")
        self.assertFalse(image_loader.is_cached("a"))
        self.assertTrue(image_loader.is_cached("b"))

    def test_evicting_an_absent_url_is_harmless(self):
        image_loader.evict("never-cached")
        self.assertEqual(image_loader.cache_size(), 0)

    def test_size_variants_are_cached_separately(self):
        image_loader._cache_put(image_loader._cache_key("a", 100, 200), FakePixbuf("a"))
        self.assertTrue(image_loader.is_cached("a", 100, 200))
        self.assertFalse(image_loader.is_cached("a"))

    def test_prefetch_skips_an_already_cached_url(self):
        self._put("a")
        calls = []
        original = image_loader.load_image_async
        image_loader.load_image_async = lambda *a, **k: calls.append(a)
        try:
            image_loader.prefetch("a")
        finally:
            image_loader.load_image_async = original
        self.assertEqual(calls, [])

    def test_prefetch_skips_an_empty_url(self):
        calls = []
        original = image_loader.load_image_async
        image_loader.load_image_async = lambda *a, **k: calls.append(a)
        try:
            image_loader.prefetch("")
        finally:
            image_loader.load_image_async = original
        self.assertEqual(calls, [])

    def test_prefetch_skips_a_url_already_in_flight(self):
        key = image_loader._cache_key("a", -1, -1)
        image_loader._inflight.add(key)
        calls = []
        original = image_loader.load_image_async
        image_loader.load_image_async = lambda *a, **k: calls.append(a)
        try:
            image_loader.prefetch("a")
        finally:
            image_loader.load_image_async = original
            image_loader._inflight.discard(key)
        self.assertEqual(calls, [])

    def test_prefetch_loads_an_uncached_url(self):
        calls = []
        original = image_loader.load_image_async
        image_loader.load_image_async = lambda *a, **k: calls.append(a)
        try:
            image_loader.prefetch("fresh")
        finally:
            image_loader.load_image_async = original
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
