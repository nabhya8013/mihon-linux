"""Tests for the Upcoming release predictions."""
import time
import unittest
from types import SimpleNamespace as NS

from mihon.core import upcoming as up

DAY = up.DAY
# A fixed "now" at local noon, so day boundaries are unambiguous.
_lt = time.localtime(1_800_000_000)
NOW = time.mktime((_lt.tm_year, _lt.tm_mon, _lt.tm_mday, 12, 0, 0, 0, 0, -1))


def manga(title="M", status="ongoing"):
    return NS(title=title, status=status)


def weekly(last_days_ago, count=5, every=7):
    return [NOW - (last_days_ago + i * every) * DAY for i in range(count)]


class IntervalTests(unittest.TestCase):
    def test_weekly(self):
        self.assertEqual(up.release_interval_days(weekly(1)), 7)

    def test_same_day_batch_counts_once(self):
        times = weekly(1) + [NOW - 1 * DAY + 60, NOW - 1 * DAY + 120]
        self.assertEqual(up.release_interval_days(times), 7)

    def test_median_ignores_one_late_chapter(self):
        days = [0, 7, 14, 30, 37, 44]
        times = [NOW - d * DAY for d in days]
        self.assertEqual(up.release_interval_days(times), 7)

    def test_too_few_releases(self):
        self.assertIsNone(up.release_interval_days(weekly(1, count=2)))

    def test_too_irregular(self):
        self.assertIsNone(up.release_interval_days(weekly(1, every=90)))

    def test_missing_dates_are_ignored(self):
        self.assertEqual(up.release_interval_days(weekly(1) + [None, 0]), 7)


class PredictTests(unittest.TestCase):
    def test_next_release_follows_the_rhythm(self):
        p = up.predict(manga(), weekly(2), NOW)
        self.assertFalse(p.overdue)
        self.assertEqual(up.day_label(p.next_release, NOW), up.day_label(NOW + 5 * DAY, NOW))

    def test_late_series_is_due_now(self):
        p = up.predict(manga(), weekly(10), NOW)
        self.assertTrue(p.overdue)

    def test_silent_for_three_intervals_is_hiatus(self):
        self.assertIsNone(up.predict(manga(), weekly(25), NOW))

    def test_finished_series_get_no_prediction(self):
        for status in ("completed", "Cancelled", "publishing finished"):
            self.assertIsNone(up.predict(manga(status=status), weekly(1), NOW))

    def test_unknown_status_still_predicted(self):
        self.assertIsNotNone(up.predict(manga(status=""), weekly(1), NOW))


class ListTests(unittest.TestCase):
    def test_sorted_overdue_first_then_soonest(self):
        a = manga("A"); b = manga("B"); c = manga("C")
        result = up.upcoming([(a, weekly(1)), (b, weekly(10)), (c, weekly(5))], now=NOW)
        self.assertEqual([p.manga.title for p in result], ["B", "C", "A"])

    def test_horizon_limits_the_list(self):
        monthly = [NOW - (1 + i * 40) * DAY for i in range(4)]
        self.assertEqual(up.upcoming([(manga(), monthly)], now=NOW, horizon_days=30), [])

    def test_group_by_day(self):
        a = manga("A"); b = manga("B"); c = manga("C")
        preds = up.upcoming([(a, weekly(6)), (b, weekly(6)), (c, weekly(10))], now=NOW)
        groups = up.group_by_day(preds, NOW)
        self.assertEqual(groups[0][0], "Due now")
        self.assertEqual(groups[1][0], "Tomorrow")
        self.assertEqual([p.manga.title for p in groups[1][1]], ["A", "B"])

    def test_day_labels(self):
        self.assertEqual(up.day_label(NOW, NOW), "Today")
        self.assertEqual(up.day_label(NOW + DAY, NOW), "Tomorrow")
        self.assertRegex(up.day_label(NOW + 3 * DAY, NOW), r"^\w+, \d+ \w+$")

    def test_describe_interval(self):
        self.assertEqual(up.describe_interval(1), "Daily")
        self.assertEqual(up.describe_interval(7), "Weekly")
        self.assertEqual(up.describe_interval(14), "Every 2 weeks")
        self.assertEqual(up.describe_interval(10), "Every 10 days")


if __name__ == "__main__":
    unittest.main()
