"""Tests for the concurrent global search fan-out."""
import threading
import time
import unittest

from mihon.core.global_search import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_TIMEOUT,
    GlobalSearch,
    SourceResult,
    flatten,
)
from mihon.core.models import Manga


class FakeSource:
    def __init__(self, source_id, name=None, results=None, delay=0.0, error=None):
        self.id = source_id
        self.name = name or source_id
        self._results = results if results is not None else []
        self._delay = delay
        self._error = error
        self.calls = []

    def search(self, filters, page=1):
        self.calls.append((filters.query, page))
        if self._delay:
            time.sleep(self._delay)
        if self._error:
            raise self._error
        return list(self._results), False


def _manga(title, source_id="", source_manga_id="", url=""):
    return Manga(
        title=title,
        source_id=source_id,
        source_manga_id=source_manga_id,
        url=url,
    )


class BasicSearchTests(unittest.TestCase):

    def test_every_source_is_searched(self):
        sources = [
            FakeSource("a", results=[_manga("One")]),
            FakeSource("b", results=[_manga("Two")]),
        ]
        results = GlobalSearch(sources).run("piece")
        self.assertEqual(len(results), 2)
        for source in sources:
            self.assertEqual(source.calls, [("piece", 1)])

    def test_result_carries_source_identity(self):
        search = GlobalSearch([FakeSource("a", name="Source A", results=[_manga("X")])])
        result = search.run("q")[0]
        self.assertEqual(result.source_id, "a")
        self.assertEqual(result.source_name, "Source A")
        self.assertEqual(result.status, STATUS_OK)

    def test_source_with_no_results_is_marked_empty(self):
        result = GlobalSearch([FakeSource("a", results=[])]).run("q")[0]
        self.assertEqual(result.status, STATUS_EMPTY)
        self.assertTrue(result.ok)

    def test_no_sources_completes_immediately(self):
        completed = []
        results = GlobalSearch([]).run("q", on_complete=completed.append)
        self.assertEqual(results, [])
        self.assertEqual(completed, [[]])

    def test_missing_source_ids_are_filled_in(self):
        source = FakeSource("mangadex", results=[_manga("Berserk", url="/m/1")])
        result = GlobalSearch([source]).run("q")[0]
        self.assertEqual(result.manga[0].source_id, "mangadex")
        self.assertEqual(result.manga[0].source_manga_id, "/m/1")

    def test_existing_source_ids_are_left_alone(self):
        source = FakeSource(
            "mangadex",
            results=[_manga("Berserk", source_id="other", source_manga_id="keep")],
        )
        result = GlobalSearch([source]).run("q")[0]
        self.assertEqual(result.manga[0].source_id, "other")
        self.assertEqual(result.manga[0].source_manga_id, "keep")

    def test_results_are_capped_per_source(self):
        source = FakeSource("a", results=[_manga(f"T{i}") for i in range(50)])
        result = GlobalSearch([source], limit_per_source=5).run("q")[0]
        self.assertEqual(result.count, 5)


class FailureTests(unittest.TestCase):

    def test_a_failing_source_does_not_stop_the_others(self):
        sources = [
            FakeSource("bad", error=RuntimeError("boom")),
            FakeSource("good", results=[_manga("Fine")]),
        ]
        by_id = {r.source_id: r for r in GlobalSearch(sources).run("q")}
        self.assertEqual(by_id["bad"].status, STATUS_ERROR)
        self.assertIn("boom", by_id["bad"].error)
        self.assertEqual(by_id["good"].status, STATUS_OK)

    def test_a_slow_source_times_out_without_blocking_the_rest(self):
        sources = [
            FakeSource("slow", delay=5.0),
            FakeSource("fast", results=[_manga("Quick")]),
        ]
        started = time.monotonic()
        by_id = {r.source_id: r for r in GlobalSearch(sources, timeout=0.3).run("q")}
        elapsed = time.monotonic() - started

        self.assertEqual(by_id["slow"].status, STATUS_TIMEOUT)
        self.assertEqual(by_id["fast"].status, STATUS_OK)
        # The fan-out must return on the timeout, not after the slow source.
        self.assertLess(elapsed, 4.0)

    def test_a_failing_callback_does_not_abort_the_search(self):
        def boom(_result):
            raise RuntimeError("ui blew up")

        sources = [FakeSource("a", results=[_manga("X")]), FakeSource("b")]
        results = GlobalSearch(sources).run("q", on_source_done=boom)
        self.assertEqual(len(results), 2)


class StreamingTests(unittest.TestCase):

    def test_results_stream_as_each_source_answers(self):
        seen = []
        sources = [
            FakeSource("slow", delay=0.25, results=[_manga("Late")]),
            FakeSource("fast", results=[_manga("Early")]),
        ]
        GlobalSearch(sources, timeout=5.0).run("q", on_source_done=lambda r: seen.append(r.source_id))
        self.assertEqual(seen, ["fast", "slow"])

    def test_on_source_done_fires_once_per_source(self):
        seen = []
        sources = [FakeSource(str(i), results=[_manga("X")]) for i in range(5)]
        GlobalSearch(sources).run("q", on_source_done=lambda r: seen.append(r.source_id))
        self.assertEqual(sorted(seen), sorted(str(i) for i in range(5)))

    def test_on_complete_receives_every_source(self):
        completed = []
        sources = [FakeSource("a", results=[_manga("X")]), FakeSource("b")]
        GlobalSearch(sources).run("q", on_complete=completed.append)
        self.assertEqual(len(completed), 1)
        self.assertEqual(len(completed[0]), 2)

    def test_sources_really_run_in_parallel(self):
        """Three 0.2s sources must finish well inside the 0.6s serial cost."""
        sources = [FakeSource(str(i), delay=0.2) for i in range(3)]
        started = time.monotonic()
        GlobalSearch(sources, max_workers=3, timeout=5.0).run("q")
        self.assertLess(time.monotonic() - started, 0.5)


class CancelTests(unittest.TestCase):

    def test_cancel_suppresses_callbacks(self):
        seen = []
        search = GlobalSearch([FakeSource("a", results=[_manga("X")])])
        search.cancel()
        search.run("q", on_source_done=seen.append, on_complete=seen.append)
        self.assertEqual(seen, [])
        self.assertTrue(search.cancelled)

    def test_cancelled_search_still_returns_its_rows(self):
        search = GlobalSearch([FakeSource("a", results=[_manga("X")])])
        search.cancel()
        results = search.run("q")
        self.assertEqual(len(results), 1)


class FlattenTests(unittest.TestCase):

    def test_flatten_merges_and_sorts_by_title(self):
        results = [
            SourceResult("a", "A", STATUS_OK, [_manga("Zebra", "a", "1")]),
            SourceResult("b", "B", STATUS_OK, [_manga("Apple", "b", "2")]),
        ]
        self.assertEqual([m.title for m in flatten(results)], ["Apple", "Zebra"])

    def test_flatten_deduplicates_identical_entries(self):
        duplicate = _manga("Same", "a", "1")
        results = [
            SourceResult("a", "A", STATUS_OK, [duplicate]),
            SourceResult("a", "A", STATUS_OK, [_manga("Same", "a", "1")]),
        ]
        self.assertEqual(len(flatten(results)), 1)

    def test_same_title_on_two_sources_is_kept_twice(self):
        """That distinction is the entire point of a migration search."""
        results = [
            SourceResult("a", "A", STATUS_OK, [_manga("Naruto", "a", "1")]),
            SourceResult("b", "B", STATUS_OK, [_manga("Naruto", "b", "1")]),
        ]
        self.assertEqual(len(flatten(results)), 2)

    def test_flatten_of_nothing(self):
        self.assertEqual(flatten([]), [])
        self.assertEqual(flatten([SourceResult("a", "A", STATUS_EMPTY, [])]), [])


if __name__ == "__main__":
    unittest.main()
