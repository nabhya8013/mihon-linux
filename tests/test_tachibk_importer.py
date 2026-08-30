"""Tests for the .tachibk importer."""
import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, text_format

from mihon.core.tachibk_importer import (
    MIHON_BACKUP_PROTO,
    ImportResult,
    import_tachibk,
    parse_backup,
)


def _build_runtime_message():
    file_proto = descriptor_pb2.FileDescriptorProto()
    text_format.Parse(MIHON_BACKUP_PROTO, file_proto)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    backup_cls = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("MihonBackup.Backup")
    )
    manga_cls = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("MihonBackup.BackupManga")
    )
    category_cls = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("MihonBackup.BackupCategory")
    )
    return backup_cls, manga_cls, category_cls


def _build_sample_backup_bytes(*, with_favorite: bool = True, with_categories: bool = True):
    backup_cls, manga_cls, category_cls = _build_runtime_message()
    backup = backup_cls()
    cat_a = category_cls()
    cat_a.name = "Reading"
    cat_a.order = 0
    cat_b = category_cls()
    cat_b.name = "Plan to Read"
    cat_b.order = 1
    backup.backupCategories.append(cat_a)
    backup.backupCategories.append(cat_b)

    m1 = manga_cls()
    m1.source = 2499283573021220255
    m1.url = "/manga/test-1"
    m1.title = "Test Manga One"
    m1.author = "Author A"
    m1.artist = "Artist A"
    m1.description = "A test manga"
    m1.status = 2
    m1.dateAdded = 1700000000000
    m1.genre.append("Action")
    m1.genre.append("Adventure")
    if with_favorite:
        m1.favorite = True
    if with_categories:
        m1.categories.append(0)
        m1.categories.append(1)
    backup.backupManga.append(m1)

    m2 = manga_cls()
    m2.source = 2499283573021220255
    m2.url = "/manga/test-2"
    m2.title = "Test Manga Two"
    m2.author = "Author B"
    if with_favorite:
        m2.favorite = False
    backup.backupManga.append(m2)

    raw = backup.SerializeToString()
    return raw, gzip.compress(raw)


class TachibkImporterTests(unittest.TestCase):
    def test_parse_plain_protobuf(self):
        raw, _ = _build_sample_backup_bytes()
        with tempfile.NamedTemporaryFile(suffix=".tachibk", delete=False) as f:
            f.write(raw)
            path = Path(f.name)
        try:
            backup = parse_backup(path)
        finally:
            path.unlink()
        self.assertEqual(len(backup.mangas), 2)
        titles = {m.title for m in backup.mangas}
        self.assertIn("Test Manga One", titles)
        self.assertEqual(backup.mangas[0].chapter_count, 0)
        self.assertEqual(backup.mangas[0].favorite, True)
        self.assertEqual(backup.mangas[1].favorite, False)

    def test_parse_gzipped_protobuf(self):
        _, gz = _build_sample_backup_bytes()
        with tempfile.NamedTemporaryFile(suffix=".tachibk", delete=False) as f:
            f.write(gz)
            path = Path(f.name)
        try:
            backup = parse_backup(path)
        finally:
            path.unlink()
        self.assertEqual(len(backup.mangas), 2)
        self.assertEqual(len(backup.categories), 2)
        self.assertEqual(backup.mangas[0].categories, [0, 1])
        self.assertEqual(backup.mangas[0].genres, ["Action", "Adventure"])

    def test_missing_favorite_field_defaults_to_true(self):
        _, gz = _build_sample_backup_bytes(with_favorite=False)
        with tempfile.NamedTemporaryFile(suffix=".tachibk", delete=False) as f:
            f.write(gz)
            path = Path(f.name)
        try:
            backup = parse_backup(path)
        finally:
            path.unlink()
        for m in backup.mangas:
            self.assertTrue(m.favorite, f"{m.title} should default to favorite=True")

    def test_dry_run_does_not_touch_db(self):
        _, gz = _build_sample_backup_bytes()
        with tempfile.NamedTemporaryFile(suffix=".tachibk", delete=False) as f:
            f.write(gz)
            path = Path(f.name)
        try:
            with patch("mihon.core.tachibk_importer.get_db") as mock_get_db:
                result = import_tachibk(path, apply=False)
        finally:
            path.unlink()
        self.assertIsInstance(result, ImportResult)
        self.assertFalse(result.applied)
        self.assertEqual(result.imported_manga, 0)
        mock_get_db.assert_not_called()

    def test_apply_imports_into_db(self):
        from mihon.core.models import Manga

        _, gz = _build_sample_backup_bytes()
        with tempfile.NamedTemporaryFile(suffix=".tachibk", delete=False) as f:
            f.write(gz)
            path = Path(f.name)
        try:
            captured = []

            class FakeDB:
                def __init__(self):
                    self.cats = []

                def get_categories(self):
                    return list(self.cats)

                def create_category(self, name):
                    captured.append(("create", name))
                    cid = len(self.cats) + 100
                    self.cats.append(type("C", (), {"id": cid, "name": name})())
                    return cid

                def upsert_manga(self, manga: Manga):
                    captured.append(("upsert", manga.title, manga.in_library))
                    return 1

                def get_manga_by_source(self, source_id, source_manga_id):
                    return type("Row", (), {"id": 1})()

                def add_manga_to_category_bulk(self, manga_ids, category_id):
                    captured.append(("bulk", manga_ids, category_id))

            with patch("mihon.core.tachibk_importer.get_db", return_value=FakeDB()):
                result = import_tachibk(path, apply=True)
        finally:
            path.unlink()

        self.assertTrue(result.applied)
        self.assertEqual(result.imported_manga, 2)
        self.assertEqual(result.errors, [])
        created_names = [c[1] for c in captured if c[0] == "create"]
        self.assertIn("Reading", created_names)
        self.assertIn("Plan to Read", created_names)
        self.assertIn("Imported", created_names)


if __name__ == "__main__":
    unittest.main()
