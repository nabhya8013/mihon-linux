"""
Tests for the library presenter.

The point of extracting this from LibraryView is that the library's filtering,
sorting and per-category preference logic can now be exercised without
instantiating a single GTK widget — which is exactly what these tests do.
"""
import json
import unittest

from mihon.core.models import Manga, ReadingStatus
from mihon.ui.library_presenter import (
    GLOBAL_PREFS_KEY,
    LibraryPresenter,
    prefs_key_for_category,
)
from mihon.ui.library_state import LibraryPreferences


class FakeCategory:
    def __init__(self, cid, name, sort_order=0):
        self.id = cid
        self.name = name
        self.sort_order = sort_order


class FakeDB:
    def __init__(self, library=None, categories=None, downloaded=None, settings=None):
        self._library = library or {}
        self._categories = categories or []
        self._downloaded = downloaded or set()
        self.settings = dict(settings or {})
        self.get_library_calls = []

    def get_library(self, category_id=None):
        self.get_library_calls.append(category_id)
        return list(self._library.get(category_id, self._library.get(None, [])))

    def get_categories(self):
        return list(self._categories)

    def get_downloaded_manga_ids(self, manga_ids):
        return {mid for mid in manga_ids if mid in self._downloaded}

    def get_setting(self, key, default=""):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value


def _manga(mid, title, unread=0, status=ReadingStatus.NONE, added=0.0, author=""):
    return Manga(
        id=mid,
        title=title,
        author=author,
        unread_count=unread,
        reading_status=status,
        added_at=added,
    )


def _sample():
    return [
        _manga(1, "Berserk", unread=3, status=ReadingStatus.READING, added=100.0),
        _manga(2, "Akira", unread=0, status=ReadingStatus.COMPLETED, added=300.0),
        _manga(3, "Chainsaw Man", unread=7, status=ReadingStatus.READING, added=200.0,
               author="Fujimoto"),
    ]


def _presenter(db=None, manga=None, categories=None, downloaded=None):
    db = db or FakeDB(downloaded=downloaded or set())
    presenter = LibraryPresenter(db)
    presenter.set_loaded(manga if manga is not None else _sample(), categories or [], downloaded or set())
    return presenter, db


class VisibilityTests(unittest.TestCase):

    def test_everything_is_visible_by_default(self):
        presenter, _ = _presenter()
        self.assertEqual(len(presenter.visible_manga), 3)

    def test_default_sort_is_by_title(self):
        presenter, _ = _presenter()
        self.assertEqual(
            [m.title for m in presenter.visible_manga],
            ["Akira", "Berserk", "Chainsaw Man"],
        )

    def test_search_matches_title(self):
        presenter, _ = _presenter()
        presenter.set_search_query("bers")
        self.assertEqual([m.title for m in presenter.visible_manga], ["Berserk"])

    def test_search_matches_author(self):
        presenter, _ = _presenter()
        presenter.set_search_query("fujimoto")
        self.assertEqual([m.title for m in presenter.visible_manga], ["Chainsaw Man"])

    def test_search_is_case_insensitive_and_trimmed(self):
        presenter, _ = _presenter()
        presenter.set_search_query("  BERSERK ")
        self.assertEqual(len(presenter.visible_manga), 1)

    def test_clearing_the_search_restores_everything(self):
        presenter, _ = _presenter()
        presenter.set_search_query("akira")
        presenter.set_search_query("")
        self.assertEqual(len(presenter.visible_manga), 3)

    def test_unread_only_filter(self):
        presenter, _ = _presenter()
        presenter.update_prefs(unread_only=True)
        self.assertEqual(
            sorted(m.title for m in presenter.visible_manga),
            ["Berserk", "Chainsaw Man"],
        )

    def test_downloaded_only_filter(self):
        presenter, _ = _presenter(downloaded={2})
        presenter.update_prefs(downloaded_only=True)
        self.assertEqual([m.title for m in presenter.visible_manga], ["Akira"])

    def test_status_filter(self):
        presenter, _ = _presenter()
        presenter.update_prefs(status_filters=[ReadingStatus.COMPLETED.value])
        self.assertEqual([m.title for m in presenter.visible_manga], ["Akira"])

    def test_sort_by_unread_descending(self):
        presenter, _ = _presenter()
        presenter.update_prefs(sort_by="unread_count", sort_desc=True)
        self.assertEqual(
            [m.title for m in presenter.visible_manga],
            ["Chainsaw Man", "Berserk", "Akira"],
        )

    def test_visible_ids_skips_unsaved_rows(self):
        presenter, _ = _presenter(manga=[_manga(1, "A"), _manga(None, "B")])
        self.assertEqual(presenter.visible_ids(), [1])

    def test_is_filtered_empty_distinguishes_from_an_empty_library(self):
        presenter, _ = _presenter()
        presenter.set_search_query("nothing matches this")
        self.assertTrue(presenter.is_filtered_empty)

        empty, _ = _presenter(manga=[])
        self.assertFalse(empty.is_filtered_empty)
        self.assertTrue(empty.is_empty)


class ObserverTests(unittest.TestCase):

    def test_observers_fire_on_a_change(self):
        presenter, _ = _presenter()
        seen = []
        presenter.subscribe(lambda p: seen.append(len(p.visible_manga)))
        presenter.set_search_query("akira")
        self.assertEqual(seen, [1])

    def test_a_no_op_change_does_not_notify(self):
        presenter, _ = _presenter()
        seen = []
        presenter.subscribe(lambda p: seen.append(1))
        presenter.set_search_query("")        # already empty
        presenter.update_prefs(unread_only=False)  # already False
        self.assertEqual(seen, [])

    def test_unsubscribe_stops_notifications(self):
        presenter, _ = _presenter()
        seen = []
        callback = lambda p: seen.append(1)
        presenter.subscribe(callback)
        presenter.unsubscribe(callback)
        presenter.set_search_query("akira")
        self.assertEqual(seen, [])

    def test_subscribing_twice_registers_once(self):
        presenter, _ = _presenter()
        seen = []
        callback = lambda p: seen.append(1)
        presenter.subscribe(callback)
        presenter.subscribe(callback)
        presenter.set_search_query("akira")
        self.assertEqual(len(seen), 1)

    def test_a_failing_observer_does_not_break_the_others(self):
        presenter, _ = _presenter()
        seen = []

        def boom(_p):
            raise RuntimeError("render failed")

        presenter.subscribe(boom)
        presenter.subscribe(lambda p: seen.append(1))
        presenter.set_search_query("akira")
        self.assertEqual(seen, [1])


class PreferenceTests(unittest.TestCase):

    def test_prefs_key_for_no_category_is_the_global_key(self):
        self.assertEqual(prefs_key_for_category(None), GLOBAL_PREFS_KEY)

    def test_prefs_key_is_per_category(self):
        self.assertEqual(prefs_key_for_category(7), "library_prefs_category_7")

    def test_changing_a_preference_persists_it(self):
        presenter, db = _presenter()
        presenter.update_prefs(sort_by="unread_count")
        stored = json.loads(db.settings[GLOBAL_PREFS_KEY])
        self.assertEqual(stored["sort_by"], "unread_count")

    def test_an_unconfigured_category_inherits_the_global_preferences(self):
        db = FakeDB(settings={GLOBAL_PREFS_KEY: LibraryPreferences(sort_by="last_read").to_json()})
        presenter = LibraryPresenter(db)
        self.assertEqual(presenter.load_preferences(5).sort_by, "last_read")

    def test_a_configured_category_keeps_its_own_preferences(self):
        db = FakeDB(settings={
            GLOBAL_PREFS_KEY: LibraryPreferences(sort_by="last_read").to_json(),
            "library_prefs_category_5": LibraryPreferences(sort_by="title").to_json(),
        })
        presenter = LibraryPresenter(db)
        self.assertEqual(presenter.load_preferences(5).sort_by, "title")

    def test_an_unknown_preference_name_is_ignored(self):
        presenter, _ = _presenter()
        self.assertFalse(presenter.update_prefs(not_a_real_field=True))

    def test_update_prefs_reports_whether_anything_changed(self):
        presenter, _ = _presenter()
        self.assertTrue(presenter.update_prefs(sort_desc=True))
        self.assertFalse(presenter.update_prefs(sort_desc=True))

    def test_reset_clears_filters_and_the_search(self):
        presenter, _ = _presenter()
        presenter.update_prefs(unread_only=True, sort_by="last_read")
        presenter.set_search_query("berserk")
        presenter.reset_prefs()
        self.assertEqual(presenter.search_query, "")
        self.assertFalse(presenter.prefs.unread_only)
        self.assertEqual(presenter.prefs.sort_by, "title")


class CategoryTests(unittest.TestCase):

    def test_switching_category_reports_a_change(self):
        presenter, _ = _presenter(categories=[FakeCategory(5, "Reading")])
        self.assertTrue(presenter.set_category(5))
        self.assertEqual(presenter.category_id, 5)

    def test_switching_to_the_same_category_is_a_no_op(self):
        presenter, _ = _presenter()
        self.assertFalse(presenter.set_category(None))

    def test_switching_category_persists_the_outgoing_preferences(self):
        presenter, db = _presenter()
        presenter.update_prefs(sort_by="last_read")
        presenter.set_category(5)
        self.assertIn(GLOBAL_PREFS_KEY, db.settings)

    def test_switching_category_drops_the_previous_rows(self):
        """Otherwise a slow reload leaves the old category's manga on screen."""
        presenter, _ = _presenter()
        presenter.set_category(5)
        self.assertEqual(presenter.visible_manga, [])

    def test_category_name_lookup(self):
        presenter, _ = _presenter(categories=[FakeCategory(5, "Reading")])
        self.assertEqual(presenter.category_name(5), "Reading")
        self.assertEqual(presenter.category_name(None), "All")
        self.assertEqual(presenter.category_name(99), "")

    def test_load_from_db_reads_the_current_category(self):
        db = FakeDB(library={None: _sample(), 5: [_manga(9, "Solo")]},
                    categories=[FakeCategory(5, "Reading")])
        presenter = LibraryPresenter(db)
        presenter.set_category(5)
        manga, categories, downloaded = presenter.load_from_db()
        self.assertEqual([m.title for m in manga], ["Solo"])
        self.assertEqual(db.get_library_calls[-1], 5)


class UpdateMangaTests(unittest.TestCase):

    def test_updating_a_loaded_manga_replaces_it(self):
        presenter, _ = _presenter()
        updated = _manga(1, "Berserk (Deluxe)")
        self.assertTrue(presenter.update_manga(updated))
        titles = [m.title for m in presenter.visible_manga]
        self.assertIn("Berserk (Deluxe)", titles)
        self.assertNotIn("Berserk", titles)

    def test_updating_an_unknown_manga_reports_false(self):
        presenter, _ = _presenter()
        self.assertFalse(presenter.update_manga(_manga(999, "Ghost")))

    def test_updating_with_no_id_reports_false(self):
        presenter, _ = _presenter()
        self.assertFalse(presenter.update_manga(_manga(None, "Unsaved")))
        self.assertFalse(presenter.update_manga(None))


if __name__ == "__main__":
    unittest.main()
