"""
Incognito mode: reading must leave no history, saved page, read mark or
tracker update while it is on, and behave normally once it is off.
"""
import importlib
import os
import tempfile
import unittest
from unittest.mock import patch

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

Gtk.init_check()
Adw.init()


class IncognitoTests(unittest.TestCase):
    def setUp(self):
        os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
        from mihon.core import database
        importlib.reload(database)
        self.db = database.get_db()

        from mihon.core.models import Chapter, Manga, Page
        self.manga_id = self.db.upsert_manga(Manga(source_id="s", source_manga_id="m", title="T"))
        self.db.upsert_chapters([Chapter(manga_id=self.manga_id, source_chapter_id="c1",
                                         chapter_number=1.0, title="")])
        self.chapter = self.db.get_chapters(self.manga_id)[0]

        from mihon.ui import reader
        with patch.object(reader, "get_db", return_value=self.db):
            self.reader = reader.ReaderView()
        self.reader._db = self.db
        self.reader._manga = self.db.get_manga_by_id(self.manga_id)
        self.reader._chapter = self.chapter
        self.reader._pages = [Page(index=i) for i in range(4)]

    def history_rows(self):
        return self.db.get_history()

    def test_off_by_default(self):
        from mihon.core.privacy import is_incognito
        self.assertFalse(is_incognito(self.db))

    def test_progress_and_history_saved_normally(self):
        self.reader._save_progress(2)
        self.assertEqual(self.db.get_chapter_by_id(self.chapter.id).last_page_read, 2)
        self.assertEqual(len(self.history_rows()), 1)

    def test_incognito_saves_nothing(self):
        from mihon.core.privacy import set_incognito
        set_incognito(self.db, True)
        with patch.object(self.reader, "_maybe_sync_tracking") as sync:
            self.reader._save_progress(3)
        self.assertEqual(self.db.get_chapter_by_id(self.chapter.id).last_page_read, 0)
        self.assertEqual(self.history_rows(), [])
        sync.assert_not_called()

    def test_incognito_does_not_mark_chapter_read(self):
        from mihon.core.privacy import set_incognito
        set_incognito(self.db, True)
        self.reader._on_chapter_finished()
        self.assertFalse(self.db.get_chapter_by_id(self.chapter.id).read)
        # The end card still shows, so reading flow is unchanged.
        self.assertTrue(self.reader._chapter_end_card.get_visible())

    def test_switching_off_resumes_recording(self):
        from mihon.core.privacy import set_incognito
        set_incognito(self.db, True)
        self.reader._save_progress(1)
        set_incognito(self.db, False)
        self.reader._save_progress(2)
        self.assertEqual(self.db.get_chapter_by_id(self.chapter.id).last_page_read, 2)
        self.assertEqual(len(self.history_rows()), 1)

    def test_finishing_normally_marks_read(self):
        self.reader._on_chapter_finished()
        self.assertTrue(self.db.get_chapter_by_id(self.chapter.id).read)


if __name__ == "__main__":
    unittest.main()
