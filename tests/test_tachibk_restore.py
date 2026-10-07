"""
Tests for applying a .tachibk backup: chapters, read progress, history,
merge vs. overwrite, preview, progress callbacks, and bad input.

These run against a real temporary database rather than a fake, because the
behaviour that matters (unique keys, upsert conflict rules, unread counts)
lives in the database layer.
"""
import gzip
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mihon.core.tachibk_importer import (
    BackupError,
    ConflictMode,
    import_tachibk,
    parse_backup,
    preview_backup,
)
from tests.test_tachibk_importer import _build_runtime_message

SOURCE = 12345  # not a built-in id, so it maps to "mihon:12345"
LOCAL_SOURCE = "mihon:12345"


def _fresh_db():
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    from mihon.core import database
    importlib.reload(database)
    return database.Database()


def _write_backup(chapters, *, favorite=True, history=(), categories=("Reading",), manga_categories=(0,)):
    """chapters: (url, name, read, last_page, number, source_order)."""
    backup_cls, manga_cls, category_cls = _build_runtime_message()
    backup = backup_cls()
    for order, name in enumerate(categories):
        cat = backup.backupCategories.add()
        cat.name = name
        cat.order = order
    manga = backup.backupManga.add()
    manga.source = SOURCE
    manga.url = "/manga/one"
    manga.title = "Backup Title"
    manga.author = "Backup Author"
    manga.favorite = favorite
    manga.categories.extend(manga_categories)
    for url, name, read, page, number, order in chapters:
        ch = manga.chapters.add()
        ch.url = url
        ch.name = name
        ch.read = read
        ch.lastPageRead = page
        ch.chapterNumber = number
        ch.sourceOrder = order
        ch.dateUpload = 1700000000000
    for url, last_read in history:
        entry = manga.history.add()
        entry.url = url
        entry.lastRead = last_read
    f = tempfile.NamedTemporaryFile(suffix=".tachibk", delete=False)
    f.write(gzip.compress(backup.SerializeToString()))
    f.close()
    return Path(f.name)


class RestoreTestBase(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()
        patcher = patch("mihon.core.tachibk_importer.get_db", return_value=self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.paths = []

    def tearDown(self):
        for p in self.paths:
            p.unlink(missing_ok=True)

    def backup(self, *args, **kwargs):
        path = _write_backup(*args, **kwargs)
        self.paths.append(path)
        return path

    def local_manga(self):
        return self.db.get_manga_by_source(LOCAL_SOURCE, "/manga/one")

    def local_chapters(self):
        return {c.source_chapter_id: c for c in self.db.get_chapters(self.local_manga().id)}


class FreshRestoreTests(RestoreTestBase):
    def test_chapters_and_progress_are_restored(self):
        path = self.backup([
            ("/c/1", "Ch 1", True, 0, 1.0, 1),
            ("/c/2", "Ch 2", False, 7, 2.0, 0),
        ])
        result = import_tachibk(path, apply=True)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.imported_chapters, 2)
        self.assertEqual(result.new_manga, 1)

        chapters = self.local_chapters()
        self.assertTrue(chapters["/c/1"].read)
        self.assertFalse(chapters["/c/2"].read)
        self.assertEqual(chapters["/c/2"].last_page_read, 7)
        self.assertEqual(chapters["/c/2"].source_order, 0)
        self.assertEqual(self.local_manga().unread_count, 1)

    def test_history_is_restored_with_original_timestamp(self):
        path = self.backup(
            [("/c/1", "Ch 1", True, 3, 1.0, 0)],
            history=[("/c/1", 1700000000000)],
        )
        import_tachibk(path, apply=True)
        history = self.db.get_history()
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(history[0]["read_at"], 1700000000.0)
        self.assertAlmostEqual(self.local_manga().last_read_at, 1700000000.0)

    def test_restoring_twice_does_not_duplicate_chapters(self):
        path = self.backup([("/c/1", "Ch 1", True, 0, 1.0, 0)])
        import_tachibk(path, apply=True)
        again = import_tachibk(path, apply=True)
        self.assertEqual(again.imported_chapters, 0)
        self.assertEqual(again.new_manga, 0)
        self.assertEqual(len(self.local_chapters()), 1)

    def test_chapter_matched_by_url_when_stored_id_differs(self):
        manga_id = self.db.upsert_manga(self._manga(in_library=True))
        from mihon.core.models import Chapter
        self.db.upsert_chapters([Chapter(
            manga_id=manga_id, source_chapter_id="uuid-1", title="Ch 1",
            chapter_number=1.0, url="/c/1",
        )])
        path = self.backup([("/c/1", "Ch 1", True, 0, 1.0, 0)])
        result = import_tachibk(path, apply=True)
        self.assertEqual(result.imported_chapters, 0)
        chapters = self.local_chapters()
        self.assertEqual(list(chapters), ["uuid-1"])
        self.assertTrue(chapters["uuid-1"].read)

    def test_progress_callback_reports_each_manga(self):
        path = self.backup([("/c/1", "Ch 1", False, 0, 1.0, 0)])
        calls = []
        import_tachibk(path, apply=True, progress=lambda done, total: calls.append((done, total)))
        self.assertEqual(calls, [(1, 1)])

    @staticmethod
    def _manga(**overrides):
        from mihon.core.models import Manga
        fields = dict(source_id=LOCAL_SOURCE, source_manga_id="/manga/one", title="Local Title",
                      author="Local Author", in_library=False)
        fields.update(overrides)
        return Manga(**fields)


class ConflictModeTests(RestoreTestBase):
    def _seed(self, *, read, page, in_library=True):
        from mihon.core.models import Chapter, Manga
        manga_id = self.db.upsert_manga(Manga(
            source_id=LOCAL_SOURCE, source_manga_id="/manga/one", title="Local Title",
            author="Local Author", in_library=in_library,
        ))
        self.db.upsert_chapters([Chapter(
            manga_id=manga_id, source_chapter_id="/c/1", title="Local Ch 1",
            chapter_number=1.0, url="/c/1", read=read, last_page_read=page,
        )])
        self.db.restore_chapter_progress(manga_id, {"/c/1": (read, page)})
        return manga_id

    def test_merge_keeps_local_metadata(self):
        self._seed(read=False, page=0)
        path = self.backup([("/c/1", "Backup Ch 1", False, 0, 1.0, 0)])
        import_tachibk(path, apply=True, mode=ConflictMode.MERGE)
        self.assertEqual(self.local_manga().title, "Local Title")
        self.assertEqual(self.local_chapters()["/c/1"].title, "Local Ch 1")

    def test_merge_never_unreads_a_chapter(self):
        self._seed(read=True, page=9)
        path = self.backup([("/c/1", "Ch 1", False, 2, 1.0, 0)])
        import_tachibk(path, apply=True, mode=ConflictMode.MERGE)
        chapter = self.local_chapters()["/c/1"]
        self.assertTrue(chapter.read)
        self.assertEqual(chapter.last_page_read, 9)

    def test_merge_marks_chapter_read_from_backup(self):
        self._seed(read=False, page=0)
        path = self.backup([("/c/1", "Ch 1", True, 0, 1.0, 0)])
        import_tachibk(path, apply=True, mode=ConflictMode.MERGE)
        self.assertTrue(self.local_chapters()["/c/1"].read)
        self.assertEqual(self.local_manga().unread_count, 0)

    def test_merge_adds_missing_chapters(self):
        self._seed(read=False, page=0)
        path = self.backup([
            ("/c/1", "Ch 1", False, 0, 1.0, 1),
            ("/c/2", "Ch 2", False, 0, 2.0, 0),
        ])
        result = import_tachibk(path, apply=True, mode=ConflictMode.MERGE)
        self.assertEqual(result.imported_chapters, 1)
        self.assertEqual(set(self.local_chapters()), {"/c/1", "/c/2"})

    def test_overwrite_replaces_metadata_and_progress(self):
        self._seed(read=True, page=9)
        path = self.backup([("/c/1", "Backup Ch 1", False, 2, 1.0, 0)])
        import_tachibk(path, apply=True, mode=ConflictMode.OVERWRITE)
        self.assertEqual(self.local_manga().title, "Backup Title")
        chapter = self.local_chapters()["/c/1"]
        self.assertEqual(chapter.title, "Backup Ch 1")
        self.assertFalse(chapter.read)
        self.assertEqual(chapter.last_page_read, 2)

    def test_favorite_in_backup_adds_browsed_manga_to_library(self):
        self._seed(read=False, page=0, in_library=False)
        path = self.backup([("/c/1", "Ch 1", False, 0, 1.0, 0)], favorite=True)
        import_tachibk(path, apply=True)
        self.assertTrue(self.local_manga().in_library)

    def test_non_favorite_never_removes_from_library(self):
        self._seed(read=False, page=0, in_library=True)
        path = self.backup([("/c/1", "Ch 1", False, 0, 1.0, 0)], favorite=False)
        import_tachibk(path, apply=True, mode=ConflictMode.OVERWRITE)
        self.assertTrue(self.local_manga().in_library)


class PreviewAndValidationTests(RestoreTestBase):
    def test_preview_counts_without_writing(self):
        path = self.backup([
            ("/c/1", "Ch 1", True, 0, 1.0, 1),
            ("/c/2", "Ch 2", False, 0, 2.0, 0),
        ])
        preview = preview_backup(path)
        self.assertEqual(
            (preview.manga, preview.chapters, preview.read_chapters, preview.existing_manga),
            (1, 2, 1, 0),
        )
        self.assertEqual(preview.new_manga, 1)
        self.assertIsNone(self.local_manga())

    def test_preview_counts_existing_manga(self):
        from mihon.core.models import Manga
        self.db.upsert_manga(Manga(source_id=LOCAL_SOURCE, source_manga_id="/manga/one", title="X"))
        preview = preview_backup(self.backup([("/c/1", "Ch 1", False, 0, 1.0, 0)]))
        self.assertEqual(preview.existing_manga, 1)
        self.assertEqual(preview.new_manga, 0)

    def test_garbage_file_is_rejected_with_clear_error(self):
        f = tempfile.NamedTemporaryFile(suffix=".tachibk", delete=False)
        f.write(b"this is definitely not a backup \xff\xfe")
        f.close()
        path = Path(f.name)
        self.paths.append(path)
        with self.assertRaises(BackupError):
            parse_backup(path)
        result = import_tachibk(path, apply=True)
        self.assertFalse(result.ok)
        self.assertIn("not a readable Mihon backup", result.errors[0])

    def test_empty_file_is_rejected(self):
        f = tempfile.NamedTemporaryFile(suffix=".tachibk", delete=False)
        f.close()
        path = Path(f.name)
        self.paths.append(path)
        with self.assertRaises(BackupError):
            parse_backup(path)

    def test_corrupt_gzip_is_rejected(self):
        f = tempfile.NamedTemporaryFile(suffix=".tachibk", delete=False)
        f.write(b"\x1f\x8b" + b"\x00" * 20)
        f.close()
        path = Path(f.name)
        self.paths.append(path)
        with self.assertRaises(BackupError):
            parse_backup(path)

    def test_categories_are_created_and_assigned(self):
        path = self.backup([("/c/1", "Ch 1", False, 0, 1.0, 0)], categories=("Reading", "Later"),
                           manga_categories=(1,))
        result = import_tachibk(path, apply=True)
        names = {c.name for c in self.db.get_categories()}
        self.assertEqual(names, {"Reading", "Later", "Imported"})
        later = next(c for c in self.db.get_categories() if c.name == "Later")
        self.assertIn(later.id, self.db.get_manga_category_ids(self.local_manga().id))
        self.assertEqual(result.imported_categories, 3)


if __name__ == "__main__":
    unittest.main()
