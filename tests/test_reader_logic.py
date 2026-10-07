"""Tests for the reader's GTK-free rules: taps, sizing, webtoon layout, chapter order."""
import unittest
from types import SimpleNamespace as NS

from mihon.core import reader_logic as rl


def ch(id, number, order=0):
    return NS(id=id, chapter_number=number, source_order=order)


class TapActionTests(unittest.TestCase):
    def test_middle_third_opens_menu(self):
        self.assertEqual(rl.tap_action(0.5, rtl=False), "menu")

    def test_ltr_right_is_forward(self):
        self.assertEqual(rl.tap_action(0.9, rtl=False), "next")
        self.assertEqual(rl.tap_action(0.1, rtl=False), "prev")

    def test_rtl_left_is_forward(self):
        self.assertEqual(rl.tap_action(0.1, rtl=True), "next")
        self.assertEqual(rl.tap_action(0.9, rtl=True), "prev")

    def test_invert_swaps_sides(self):
        self.assertEqual(rl.tap_action(0.9, rtl=False, invert=True), "prev")
        self.assertEqual(rl.tap_action(0.1, rtl=True, invert=True), "prev")


class FitSizeTests(unittest.TestCase):
    def test_fit_page_tall_image_limited_by_height(self):
        self.assertEqual(rl.fit_sizes([(1000, 2000)], 800, 600), [(300, 600)])

    def test_fit_page_wide_image_limited_by_width(self):
        self.assertEqual(rl.fit_sizes([(2000, 1000)], 800, 600), [(800, 400)])

    def test_fit_width_runs_past_the_viewport(self):
        # This is what lets a tall page scroll instead of being squashed.
        self.assertEqual(rl.fit_sizes([(1000, 2000)], 800, 600, "fit_width"), [(800, 1600)])

    def test_zoom_scales_the_result(self):
        self.assertEqual(rl.fit_sizes([(1000, 2000)], 800, 600, zoom=2.0), [(600, 1200)])
        self.assertEqual(rl.fit_sizes([(1000, 2000)], 800, 600, zoom=0.5), [(150, 300)])

    def test_zoom_is_clamped(self):
        self.assertEqual(rl.fit_sizes([(100, 100)], 100, 100, zoom=50), [(300, 300)])

    def test_aspect_ratio_is_kept(self):
        (w, h), = rl.fit_sizes([(1200, 1700)], 1000, 700, "fit_width", 1.3)
        self.assertAlmostEqual(w / h, 1200 / 1700, places=2)

    def test_two_pages_share_a_height_and_fit_together(self):
        sizes = rl.fit_sizes([(1000, 1500), (1000, 1500)], 1004, 2000, spacing=4)
        self.assertEqual(sizes[0][1], sizes[1][1])
        self.assertLessEqual(sizes[0][0] + sizes[1][0] + 4, 1004)

    def test_missing_image_or_viewport_gives_zero(self):
        self.assertEqual(rl.fit_sizes([(0, 0)], 800, 600), [(0, 0)])
        self.assertEqual(rl.fit_sizes([(100, 100)], 0, 600), [(0, 0)])


class WebtoonLayoutTests(unittest.TestCase):
    def test_strip_height_follows_aspect(self):
        self.assertEqual(rl.strip_height(800, 3200, 400), 1600)
        # A short strip stays short: no 800 px floor padding it out.
        self.assertEqual(rl.strip_height(800, 200, 800), 200)

    def test_unloaded_strip_gets_a_placeholder(self):
        self.assertEqual(rl.strip_height(0, 0, 400), 600)

    def test_page_at_offset(self):
        tops = [0, 100, 300, 600]
        self.assertEqual(rl.page_at_offset(tops, 0), 0)
        self.assertEqual(rl.page_at_offset(tops, 99), 0)
        self.assertEqual(rl.page_at_offset(tops, 100), 1)
        self.assertEqual(rl.page_at_offset(tops, 5000), 3)
        self.assertEqual(rl.page_at_offset([], 50), 0)

    def test_window_range(self):
        self.assertEqual(list(rl.window_range(5, 20, 2, 3)), [3, 4, 5, 6, 7, 8])
        self.assertEqual(list(rl.window_range(0, 20, 2, 3)), [0, 1, 2, 3])
        self.assertEqual(list(rl.window_range(19, 20, 2, 3)), [17, 18, 19])
        self.assertEqual(list(rl.window_range(3, 0, 2, 3)), [])


class ChapterOrderTests(unittest.TestCase):
    def test_source_order_puts_unnumbered_chapters_in_place(self):
        # Source lists newest first: source_order 0 is newest.
        chapters = [ch(1, 2.0, 0), ch(2, -1.0, 1), ch(3, 1.0, 2)]
        self.assertEqual([c.id for c in rl.reading_order(chapters)], [3, 2, 1])

    def test_next_and_previous_follow_source_order(self):
        chapters = [ch(1, 2.0, 0), ch(2, -1.0, 1), ch(3, 1.0, 2)]
        self.assertEqual(rl.adjacent_chapter(chapters, chapters[2], 1).id, 2)
        self.assertEqual(rl.adjacent_chapter(chapters, chapters[1], 1).id, 1)
        self.assertEqual(rl.adjacent_chapter(chapters, chapters[1], -1).id, 3)

    def test_ends_return_none(self):
        chapters = [ch(1, 2.0, 0), ch(3, 1.0, 1)]
        self.assertIsNone(rl.adjacent_chapter(chapters, chapters[0], 1))
        self.assertIsNone(rl.adjacent_chapter(chapters, chapters[1], -1))

    def test_without_source_order_falls_back_to_numbers(self):
        chapters = [ch(5, 3.0), ch(6, 1.0), ch(7, 2.0)]
        self.assertEqual([c.id for c in rl.reading_order(chapters)], [6, 7, 5])
        self.assertEqual(rl.adjacent_chapter(chapters, chapters[1], 1).id, 7)

    def test_decimal_chapters_are_not_skipped(self):
        chapters = [ch(1, 1.0), ch(2, 1.5), ch(3, 2.0)]
        self.assertEqual(rl.adjacent_chapter(chapters, chapters[0], 1).id, 2)

    def test_unknown_current_uses_numbers(self):
        chapters = [ch(1, 1.0), ch(2, 2.0)]
        stray = ch(None, 1.0)
        self.assertEqual(rl.adjacent_chapter(chapters, stray, 1).id, 2)


if __name__ == "__main__":
    unittest.main()
