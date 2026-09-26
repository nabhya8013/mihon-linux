"""
Tests for source-order chapter storage and SManga.initialized.

Chapter number is meaningless on sources that do not number their chapters,
which is why the order the source returned is stored alongside it.
"""
import importlib
import os
import tempfile
import unittest


def _fresh_db():
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    from mihon.core import database
    importlib.reload(database)
    return database.Database()


class SourceOrderTests(unittest.TestCase):

    def setUp(self):
        from mihon.core.models import Chapter, Manga
        self.Chapter = Chapter
        self.db = _fresh_db()
        self.manga_id = self.db.upsert_manga(
            Manga(source_id="s", source_manga_id="m1", title="T", in_library=True)
        )

    def _add(self, entries):
        """entries: (source_id, number, source_order, uploaded_at)."""
        self.db.upsert_chapters([
            self.Chapter(
                manga_id=self.manga_id,
                source_chapter_id=cid,
                title=cid,
                chapter_number=number,
                source_order=order,
                uploaded_at=uploaded,
            )
            for cid, number, order, uploaded in entries
        ])

    def test_source_order_is_stored_and_read_back(self):
        self._add([("a", 1.0, 2, 100.0), ("b", 2.0, 1, 200.0)])
        by_id = {c.source_chapter_id: c for c in self.db.get_chapters(self.manga_id)}
        self.assertEqual(by_id["a"].source_order, 2)
        self.assertEqual(by_id["b"].source_order, 1)

    def test_default_sort_is_by_chapter_number_descending(self):
        self._add([("a", 1.0, 2, 100.0), ("b", 2.0, 1, 200.0)])
        chapters = self.db.get_chapters(self.manga_id)
        self.assertEqual([c.source_chapter_id for c in chapters], ["b", "a"])

    def test_source_sort_uses_the_order_the_source_returned(self):
        """Unnumbered chapters all report -1, so only source order separates them."""
        self._add([
            ("prologue", -1.0, 0, 300.0),
            ("part-one", -1.0, 1, 200.0),
            ("part-two", -1.0, 2, 100.0),
        ])
        chapters = self.db.get_chapters(self.manga_id, sort="source")
        self.assertEqual(
            [c.source_chapter_id for c in chapters],
            ["prologue", "part-one", "part-two"],
        )

    def test_number_sort_breaks_ties_on_source_order(self):
        self._add([("a", -1.0, 1, 0.0), ("b", -1.0, 0, 0.0)])
        chapters = self.db.get_chapters(self.manga_id)
        self.assertEqual([c.source_chapter_id for c in chapters], ["b", "a"])

    def test_upload_sort_is_newest_first(self):
        self._add([("old", 1.0, 1, 100.0), ("new", 2.0, 0, 900.0)])
        chapters = self.db.get_chapters(self.manga_id, sort="upload")
        self.assertEqual([c.source_chapter_id for c in chapters], ["new", "old"])

    def test_an_unknown_sort_falls_back_to_chapter_number(self):
        self._add([("a", 1.0, 0, 0.0), ("b", 2.0, 1, 0.0)])
        chapters = self.db.get_chapters(self.manga_id, sort="nonsense")
        self.assertEqual([c.source_chapter_id for c in chapters], ["b", "a"])

    def test_re_upserting_updates_the_source_order(self):
        """A source that reorders its list must not leave stale positions."""
        self._add([("a", 1.0, 5, 0.0)])
        self._add([("a", 1.0, 0, 0.0)])
        self.assertEqual(self.db.get_chapters(self.manga_id)[0].source_order, 0)

    def test_read_state_survives_a_re_upsert(self):
        self._add([("a", 1.0, 0, 0.0)])
        chapter = self.db.get_chapters(self.manga_id)[0]
        self.db.mark_chapter_read(chapter.id, page=7)
        self._add([("a", 1.0, 0, 0.0)])
        refreshed = self.db.get_chapters(self.manga_id)[0]
        self.assertTrue(refreshed.read)
        self.assertEqual(refreshed.last_page_read, 7)


class InitializedTests(unittest.TestCase):

    def setUp(self):
        from mihon.core.models import Manga
        self.Manga = Manga
        self.db = _fresh_db()

    def test_a_browse_listing_is_not_initialized(self):
        mid = self.db.upsert_manga(
            self.Manga(source_id="s", source_manga_id="m", title="T")
        )
        self.assertFalse(self.db.get_manga_by_id(mid).initialized)

    def test_a_details_fetch_marks_it_initialized(self):
        mid = self.db.upsert_manga(
            self.Manga(source_id="s", source_manga_id="m", title="T", initialized=True)
        )
        self.assertTrue(self.db.get_manga_by_id(mid).initialized)

    def test_a_later_listing_never_downgrades_it(self):
        """A search result carries less than the details call did."""
        mid = self.db.upsert_manga(
            self.Manga(source_id="s", source_manga_id="m", title="T", initialized=True)
        )
        self.db.upsert_manga(
            self.Manga(source_id="s", source_manga_id="m", title="T")
        )
        self.assertTrue(self.db.get_manga_by_id(mid).initialized)


class MigrationTests(unittest.TestCase):

    def test_an_existing_database_gains_the_new_columns(self):
        """CREATE TABLE IF NOT EXISTS never alters a table that already exists."""
        import sqlite3
        os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
        from mihon.core import database
        importlib.reload(database)

        # Build the pre-migration shape by hand.
        database.ensure_dirs()
        conn = sqlite3.connect(str(database.DB_PATH))
        conn.executescript("""
            -- The shape these tables had before source_order, initialized
            -- and the tracker columns were added.
            CREATE TABLE manga (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                source_manga_id TEXT NOT NULL,
                title TEXT NOT NULL,
                in_library INTEGER DEFAULT 0,
                UNIQUE(source_id, source_manga_id)
            );
            CREATE TABLE chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                manga_id INTEGER NOT NULL,
                source_chapter_id TEXT NOT NULL,
                UNIQUE(manga_id, source_chapter_id)
            );
            CREATE TABLE history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                manga_id INTEGER NOT NULL
            );
            CREATE TABLE manga_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                manga_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                UNIQUE(manga_id, provider)
            );
        """)
        conn.commit()
        conn.close()

        db = database.Database()
        chapter_columns = {
            r["name"] for r in db.conn.execute("PRAGMA table_info(chapters)")
        }
        manga_columns = {
            r["name"] for r in db.conn.execute("PRAGMA table_info(manga)")
        }
        tracking_columns = {
            r["name"] for r in db.conn.execute("PRAGMA table_info(manga_tracking)")
        }

        self.assertIn("source_order", chapter_columns)
        self.assertIn("initialized", manga_columns)
        self.assertIn("remote_id", tracking_columns)

    def test_migrating_twice_is_harmless(self):
        db = _fresh_db()
        db._migrate_schema()
        db._migrate_schema()
        self.assertIn(
            "source_order",
            {r["name"] for r in db.conn.execute("PRAGMA table_info(chapters)")},
        )


if __name__ == "__main__":
    unittest.main()
