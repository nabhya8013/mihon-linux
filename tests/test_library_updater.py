"""
Tests for LibraryUpdater's skip_dropped and category-exclusion filters.

Each test gets an isolated database via a fresh XDG_DATA_HOME and module
reload (same pattern as test_database_concurrency.py's _fresh_db(), extended
to library_updater.py), and a fake extension that reports no new chapters so
focus stays on which manga get visited rather than chapter-diffing.
"""
import importlib
import os
import tempfile
import unittest
from unittest.mock import patch


def _fresh_updater():
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    from mihon.core import database
    importlib.reload(database)
    from mihon.core import library_updater
    importlib.reload(library_updater)
    return library_updater


class FakeExtension:
    def get_chapters(self, manga):
        return []


class LibraryUpdaterFilterTests(unittest.TestCase):

    def setUp(self):
        self.mod = _fresh_updater()
        self.db = self.mod.get_db()
        self.updater = self.mod.LibraryUpdater()

        from mihon.core.models import Manga, ReadingStatus
        self.Manga = Manga
        self.ReadingStatus = ReadingStatus

        self.reading = self._add_manga("Reading", ReadingStatus.READING)
        self.dropped = self._add_manga("Dropped", ReadingStatus.DROPPED)

    def _add_manga(self, title, reading_status):
        manga = self.Manga(
            source_id="fake", source_manga_id=title, title=title,
            in_library=True, reading_status=reading_status,
        )
        manga.id = self.db.upsert_manga(manga)
        return manga

    def _run(self, **kwargs):
        with patch.object(self.mod, "get_registry") as get_registry:
            registry = get_registry.return_value
            registry.get.return_value = FakeExtension()
            return self.updater.check_updates(**kwargs)

    def test_without_skip_dropped_everything_is_checked(self):
        summary = self._run()
        self.assertEqual(summary.checked_manga, 2)

    def test_skip_dropped_excludes_dropped_manga(self):
        summary = self._run(skip_dropped=True)
        self.assertEqual(summary.checked_manga, 1)

    def test_manual_check_ignores_skip_dropped_by_default(self):
        summary = self._run()  # skip_dropped defaults to False, as the button uses
        self.assertEqual(summary.checked_manga, 2)

    def test_excluded_category_skips_its_manga(self):
        cat_id = self.db.create_category("Plan to Read")
        self.db.set_manga_categories(self.reading.id, [cat_id])
        summary = self._run(excluded_category_ids=[cat_id])
        self.assertEqual(summary.checked_manga, 1)  # only the dropped one left

    def test_manga_with_no_categories_is_never_excluded_by_category(self):
        cat_id = self.db.create_category("Something Else")
        summary = self._run(excluded_category_ids=[cat_id])
        self.assertEqual(summary.checked_manga, 2)

    def test_empty_exclusion_list_excludes_nothing(self):
        summary = self._run(excluded_category_ids=[])
        self.assertEqual(summary.checked_manga, 2)

    def test_skip_dropped_and_excluded_category_combine(self):
        cat_id = self.db.create_category("Plan to Read")
        self.db.set_manga_categories(self.reading.id, [cat_id])
        summary = self._run(skip_dropped=True, excluded_category_ids=[cat_id])
        self.assertEqual(summary.checked_manga, 0)


class LibraryUpdaterTimestampTests(LibraryUpdaterFilterTests):
    """A library update counts as a chapter fetch, so opening a manga right
    afterwards does not fetch the same list again."""

    def test_successful_fetch_stamps_the_manga(self):
        from mihon.core.models import Chapter

        class WithChapters:
            def get_chapters(self, manga):
                return [Chapter(source_chapter_id="c1", title="1", chapter_number=1.0)]

        with patch.object(self.mod, "get_registry") as get_registry:
            get_registry.return_value.get.return_value = WithChapters()
            self.updater.check_updates()
        self.assertIsNotNone(self.db.get_manga_by_id(self.reading.id).chapters_fetched_at)

    def test_empty_answer_does_not_stamp_the_manga(self):
        self._run()  # FakeExtension returns no chapters
        self.assertIsNone(self.db.get_manga_by_id(self.reading.id).chapters_fetched_at)


if __name__ == "__main__":
    unittest.main()
