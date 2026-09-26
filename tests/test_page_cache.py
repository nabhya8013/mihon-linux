"""Tests for the reader's sliding-window prefetch and spread detection."""
import unittest
from dataclasses import dataclass
from typing import Optional

from mihon.core.page_cache import (
    AUTO_DOUBLE_MIN_WIDTH,
    DEFAULT_AHEAD,
    DEFAULT_BEHIND,
    PageCache,
    SPREAD_ASPECT_RATIO,
    is_spread,
    page_url,
    pixbuf_is_spread,
    should_auto_double,
)


@dataclass
class FakePage:
    index: int = 0
    url: str = ""
    image_url: str = ""
    local_path: str = ""


class FakePixbuf:
    def __init__(self, width, height):
        self._w, self._h = width, height

    def get_width(self):
        return self._w

    def get_height(self):
        return self._h


class ExplodingPixbuf:
    def get_width(self):
        raise RuntimeError("pixbuf is gone")

    def get_height(self):
        raise RuntimeError("pixbuf is gone")


def _pages(n, local=False):
    return [
        FakePage(
            index=i,
            url=f"https://example.invalid/p{i}",
            image_url=f"https://example.invalid/p{i}",
            local_path=f"/tmp/p{i}.jpg" if local else "",
        )
        for i in range(n)
    ]


class Recorder:
    def __init__(self):
        self.prefetched = []
        self.evicted = []

    def prefetch(self, url):
        self.prefetched.append(url)

    def evict(self, url):
        self.evicted.append(url)


def _cache(ahead=2, behind=1):
    rec = Recorder()
    return PageCache(ahead=ahead, behind=behind, prefetch=rec.prefetch, evict=rec.evict), rec


class PageUrlTests(unittest.TestCase):

    def test_prefers_image_url(self):
        self.assertEqual(page_url(FakePage(url="a", image_url="b")), "b")

    def test_falls_back_to_url(self):
        self.assertEqual(page_url(FakePage(url="a")), "a")

    def test_local_pages_have_no_url_to_prefetch(self):
        self.assertEqual(page_url(FakePage(url="a", local_path="/tmp/x.jpg")), "")

    def test_none_page(self):
        self.assertEqual(page_url(None), "")


class WindowTests(unittest.TestCase):

    def test_window_size_counts_the_current_page(self):
        cache, _ = _cache(ahead=3, behind=2)
        self.assertEqual(cache.window_size, 6)

    def test_window_is_current_page_first(self):
        cache, _ = _cache(ahead=2, behind=1)
        cache.set_pages(_pages(10))
        self.assertEqual(cache.window_indices(5)[0], 5)

    def test_window_covers_ahead_and_behind(self):
        cache, _ = _cache(ahead=2, behind=1)
        cache.set_pages(_pages(10))
        self.assertEqual(sorted(cache.window_indices(5)), [4, 5, 6, 7])

    def test_window_clamps_at_the_start(self):
        cache, _ = _cache(ahead=2, behind=2)
        cache.set_pages(_pages(10))
        self.assertEqual(sorted(cache.window_indices(0)), [0, 1, 2])

    def test_window_clamps_at_the_end(self):
        cache, _ = _cache(ahead=2, behind=2)
        cache.set_pages(_pages(5))
        self.assertEqual(sorted(cache.window_indices(4)), [2, 3, 4])

    def test_window_of_an_empty_chapter_is_empty(self):
        cache, _ = _cache()
        self.assertEqual(cache.window_indices(0), [])

    def test_out_of_range_index_is_clamped(self):
        cache, _ = _cache(ahead=1, behind=1)
        cache.set_pages(_pages(3))
        self.assertEqual(sorted(cache.window_indices(99)), [1, 2])
        self.assertEqual(sorted(cache.window_indices(-5)), [0, 1])

    def test_set_window_resizes(self):
        cache, _ = _cache(ahead=1, behind=1)
        cache.set_pages(_pages(10))
        cache.set_window(ahead=4, behind=0)
        self.assertEqual(sorted(cache.window_indices(0)), [0, 1, 2, 3, 4])

    def test_negative_window_sizes_clamp_to_zero(self):
        cache, _ = _cache()
        cache.set_window(ahead=-3, behind=-1)
        self.assertEqual(cache.window_size, 1)


class FocusTests(unittest.TestCase):

    def test_focus_prefetches_the_window(self):
        cache, rec = _cache(ahead=2, behind=1)
        cache.set_pages(_pages(10))
        cache.focus(5)
        self.assertEqual(
            sorted(rec.prefetched),
            sorted(f"https://example.invalid/p{i}" for i in (4, 5, 6, 7)),
        )

    def test_current_page_is_prefetched_first(self):
        cache, rec = _cache(ahead=2, behind=1)
        cache.set_pages(_pages(10))
        cache.focus(5)
        self.assertEqual(rec.prefetched[0], "https://example.invalid/p5")

    def test_refocusing_the_same_page_does_not_refetch(self):
        cache, rec = _cache(ahead=2, behind=1)
        cache.set_pages(_pages(10))
        cache.focus(5)
        count = len(rec.prefetched)
        cache.focus(5)
        self.assertEqual(len(rec.prefetched), count)

    def test_moving_forward_only_fetches_the_new_edge(self):
        cache, rec = _cache(ahead=2, behind=1)
        cache.set_pages(_pages(10))
        cache.focus(5)          # warms 4,5,6,7
        rec.prefetched.clear()
        cache.focus(6)          # warms 5,6,7,8 — only 8 is new
        self.assertEqual(rec.prefetched, ["https://example.invalid/p8"])

    def test_pages_leaving_the_window_are_evicted(self):
        cache, rec = _cache(ahead=2, behind=1)
        cache.set_pages(_pages(10))
        cache.focus(5)          # 4,5,6,7
        cache.focus(6)          # 5,6,7,8 — page 4 falls out
        self.assertEqual(rec.evicted, ["https://example.invalid/p4"])

    def test_eviction_happens_before_prefetch(self):
        """Otherwise a large chapter briefly holds two full windows."""
        order = []
        cache = PageCache(
            ahead=1, behind=0,
            prefetch=lambda u: order.append(("prefetch", u)),
            evict=lambda u: order.append(("evict", u)),
        )
        cache.set_pages(_pages(10))
        cache.focus(0)
        order.clear()
        cache.focus(5)
        self.assertEqual(order[0][0], "evict")

    def test_local_pages_are_never_prefetched(self):
        cache, rec = _cache()
        cache.set_pages(_pages(5, local=True))
        cache.focus(2)
        self.assertEqual(rec.prefetched, [])

    def test_focus_on_an_empty_chapter_is_a_no_op(self):
        cache, rec = _cache()
        cache.focus(0)
        self.assertEqual(rec.prefetched, [])
        self.assertIsNone(cache.current_index)

    def test_clear_evicts_everything_warm(self):
        cache, rec = _cache(ahead=2, behind=1)
        cache.set_pages(_pages(10))
        cache.focus(5)
        warm = cache.warm_urls
        cache.clear()
        self.assertEqual(sorted(rec.evicted), sorted(warm))
        self.assertEqual(cache.warm_urls, set())

    def test_new_chapter_drops_the_previous_window(self):
        cache, rec = _cache(ahead=1, behind=0)
        cache.set_pages(_pages(5))
        cache.focus(0)
        rec.evicted.clear()
        cache.set_pages(_pages(5))
        self.assertEqual(len(rec.evicted), 2)

    def test_a_failing_prefetch_does_not_break_the_window(self):
        def boom(_url):
            raise RuntimeError("network down")

        cache = PageCache(ahead=1, behind=0, prefetch=boom, evict=lambda u: None)
        cache.set_pages(_pages(5))
        cache.focus(0)
        self.assertEqual(cache.current_index, 0)

    def test_a_failing_evict_does_not_break_the_window(self):
        def boom(_url):
            raise RuntimeError("cache is gone")

        cache = PageCache(ahead=1, behind=0, prefetch=lambda u: None, evict=boom)
        cache.set_pages(_pages(5))
        cache.focus(0)
        cache.focus(3)
        self.assertEqual(cache.current_index, 3)


class SpreadDetectionTests(unittest.TestCase):

    def test_landscape_image_is_a_spread(self):
        self.assertTrue(is_spread(2000, 1400))

    def test_portrait_page_is_not_a_spread(self):
        self.assertFalse(is_spread(1000, 1500))

    def test_threshold_is_inclusive(self):
        self.assertTrue(is_spread(int(1000 * SPREAD_ASPECT_RATIO), 1000))

    def test_just_below_the_threshold_is_not_a_spread(self):
        self.assertFalse(is_spread(1299, 1000))

    def test_zero_dimensions_are_not_a_spread(self):
        self.assertFalse(is_spread(0, 0))
        self.assertFalse(is_spread(1000, 0))

    def test_custom_ratio(self):
        self.assertTrue(is_spread(1100, 1000, ratio=1.05))
        self.assertFalse(is_spread(1100, 1000, ratio=1.5))

    def test_pixbuf_wrapper(self):
        self.assertTrue(pixbuf_is_spread(FakePixbuf(2000, 1400)))
        self.assertFalse(pixbuf_is_spread(FakePixbuf(1000, 1500)))

    def test_pixbuf_wrapper_tolerates_none(self):
        self.assertFalse(pixbuf_is_spread(None))

    def test_pixbuf_wrapper_tolerates_a_broken_pixbuf(self):
        self.assertFalse(pixbuf_is_spread(ExplodingPixbuf()))


class AutoDoubleTests(unittest.TestCase):

    def test_wide_window_enables_double_page(self):
        self.assertTrue(should_auto_double(AUTO_DOUBLE_MIN_WIDTH))
        self.assertTrue(should_auto_double(2560))

    def test_narrow_window_stays_single_page(self):
        self.assertFalse(should_auto_double(AUTO_DOUBLE_MIN_WIDTH - 1))
        self.assertFalse(should_auto_double(1280))

    def test_unknown_width_stays_single_page(self):
        self.assertFalse(should_auto_double(0))
        self.assertFalse(should_auto_double(None))

    def test_custom_threshold(self):
        self.assertTrue(should_auto_double(1000, min_width=900))


class DefaultsTests(unittest.TestCase):

    def test_defaults_favour_reading_forward(self):
        self.assertGreater(DEFAULT_AHEAD, DEFAULT_BEHIND)


if __name__ == "__main__":
    unittest.main()
