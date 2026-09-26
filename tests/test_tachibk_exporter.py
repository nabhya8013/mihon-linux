"""
Tests for the .tachibk exporter.

The important property is symmetry: anything the exporter writes must come
back out of mihon.core.tachibk_importer unchanged, because that is what a
phone restoring the file will do.
"""
import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mihon.core.models import Chapter, Manga, ReadingStatus
from mihon.core.tachibk_exporter import (
    build_backup,
    default_backup_name,
    export_tachibk,
    resolve_source_id,
    tachiyomi_source_id,
)
from mihon.core.tachibk_importer import parse_backup


class FakeDB:
    """Minimal stand-in for mihon.core.database.Database."""

    def __init__(self, manga=None, chapters=None, categories=None, memberships=None):
        self._manga = manga or []
        self._chapters = chapters or {}
        self._categories = categories or []
        self._memberships = memberships or {}

    def get_library(self, category_id=None):
        return list(self._manga)

    def get_chapters(self, manga_id):
        # The real query returns chapter_number DESC.
        return list(self._chapters.get(manga_id, []))

    def get_categories(self):
        return list(self._categories)

    def get_manga_category_ids(self, manga_id):
        return list(self._memberships.get(manga_id, []))


def _category(cid, name, order):
    return type("Category", (), {"id": cid, "name": name, "sort_order": order})()


def _sample_db():
    manga = Manga(
        id=1,
        source_id="mihon:2499283573021220255",
        source_manga_id="/manga/one-piece",
        title="One Piece",
        author="Eiichiro Oda",
        artist="Eiichiro Oda",
        description="Pirates.",
        genres=["Action", "Adventure"],
        status="ongoing",
        cover_url="https://example.invalid/op.jpg",
        in_library=True,
        chapter_count=2,
        added_at=1_700_000_000.0,
        last_read_at=1_700_000_500.0,
    )
    other = Manga(
        id=2,
        source_id="mangadex",
        source_manga_id="abc-123",
        title="Berserk",
        status="on hiatus",
        in_library=True,
        added_at=1_600_000_000.0,
    )
    chapters = {
        1: [
            Chapter(
                id=20, manga_id=1, source_chapter_id="c2", title="Chapter 2",
                chapter_number=2.0, url="/manga/one-piece/2", read=False,
                last_page_read=0, uploaded_at=1_690_000_000.0,
                fetched_at=1_695_000_000.0,
            ),
            Chapter(
                id=10, manga_id=1, source_chapter_id="c1", title="Chapter 1",
                chapter_number=1.0, url="/manga/one-piece/1", read=True,
                last_page_read=17, uploaded_at=1_680_000_000.0,
                fetched_at=1_695_000_000.0, scanlator="Scans",
            ),
        ],
        2: [],
    }
    categories = [_category(5, "Reading", 0), _category(9, "Plan to Read", 1)]
    memberships = {1: [9], 2: [5, 9]}
    return FakeDB(
        manga=[manga, other],
        chapters=chapters,
        categories=categories,
        memberships=memberships,
    )


class SourceIdTests(unittest.TestCase):

    def test_tachiyomi_source_id_matches_kotlin_algorithm(self):
        """MD5 of "name/lang/version", first 8 bytes big-endian, sign bit cleared."""
        key = "mangadex/all/1"
        digest = hashlib.md5(key.encode()).digest()
        expected = int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF
        self.assertEqual(tachiyomi_source_id("MangaDex", "all", 1), expected)

    def test_source_id_is_always_non_negative(self):
        for name in ["a", "b", "mangafire", "allmanga", "zzz"]:
            self.assertGreaterEqual(tachiyomi_source_id(name, "en"), 0)

    def test_resolve_round_trips_an_imported_numeric_id(self):
        self.assertEqual(resolve_source_id("mihon:123456789"), 123456789)

    def test_resolve_hashes_a_builtin_source_name(self):
        self.assertEqual(
            resolve_source_id("mangadex"),
            tachiyomi_source_id("mangadex", "all"),
        )

    def test_resolve_handles_empty_and_malformed_ids(self):
        self.assertEqual(resolve_source_id(""), 0)
        self.assertEqual(resolve_source_id("mihon:not-a-number"), 0)


class BuildBackupTests(unittest.TestCase):

    def _build(self):
        with patch("mihon.core.tachibk_exporter.get_db", return_value=_sample_db()):
            return build_backup()

    def test_writes_every_library_manga(self):
        backup, chapters, categories = self._build()
        self.assertEqual(len(backup.backupManga), 2)
        self.assertEqual(chapters, 2)
        self.assertEqual(categories, 2)

    def test_status_string_maps_to_android_enum(self):
        backup, _, _ = self._build()
        by_title = {m.title: m for m in backup.backupManga}
        self.assertEqual(by_title["One Piece"].status, 1)    # ongoing
        self.assertEqual(by_title["Berserk"].status, 6)      # on hiatus

    def test_unknown_status_becomes_zero(self):
        db = FakeDB(manga=[Manga(id=1, title="X", status="weird", in_library=True)])
        with patch("mihon.core.tachibk_exporter.get_db", return_value=db):
            backup, _, _ = build_backup()
        self.assertEqual(backup.backupManga[0].status, 0)

    def test_timestamps_are_milliseconds(self):
        backup, _, _ = self._build()
        one_piece = backup.backupManga[0]
        self.assertEqual(one_piece.dateAdded, 1_700_000_000_000)
        self.assertEqual(one_piece.chapters[0].dateUpload, 1_680_000_000_000)

    def test_chapters_are_written_in_source_order(self):
        """The DB returns newest first; the backup must be oldest first."""
        backup, _, _ = self._build()
        one_piece = backup.backupManga[0]
        self.assertEqual([c.name for c in one_piece.chapters],
                         ["Chapter 1", "Chapter 2"])
        self.assertEqual([c.sourceOrder for c in one_piece.chapters], [0, 1])

    def test_chapter_read_state_survives(self):
        backup, _, _ = self._build()
        first = backup.backupManga[0].chapters[0]
        self.assertTrue(first.read)
        self.assertEqual(first.lastPageRead, 17)
        self.assertEqual(first.scanlator, "Scans")

    def test_categories_are_written_by_order_not_row_id(self):
        backup, _, _ = self._build()
        self.assertEqual([c.name for c in backup.backupCategories],
                         ["Reading", "Plan to Read"])
        self.assertEqual([c.order for c in backup.backupCategories], [0, 1])
        by_title = {m.title: m for m in backup.backupManga}
        # Row id 9 is order 1; row id 5 is order 0.
        self.assertEqual(list(by_title["One Piece"].categories), [1])
        self.assertEqual(list(by_title["Berserk"].categories), [0, 1])

    def test_history_records_the_last_read_chapter(self):
        backup, _, _ = self._build()
        history = backup.backupManga[0].history
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].url, "/manga/one-piece/1")
        self.assertEqual(history[0].lastRead, 1_700_000_500_000)

    def test_no_history_when_nothing_was_read(self):
        backup, _, _ = self._build()
        self.assertEqual(len(backup.backupManga[1].history), 0)

    def test_each_distinct_source_is_listed_once(self):
        backup, _, _ = self._build()
        self.assertEqual(len(backup.backupSources), 2)

    def test_empty_library_produces_a_valid_empty_backup(self):
        with patch("mihon.core.tachibk_exporter.get_db", return_value=FakeDB()):
            backup, chapters, categories = build_backup()
        self.assertEqual(len(backup.backupManga), 0)
        self.assertEqual(chapters, 0)
        self.assertEqual(categories, 0)


class ExportFileTests(unittest.TestCase):

    def _export(self, path):
        with patch("mihon.core.tachibk_exporter.get_db", return_value=_sample_db()):
            return export_tachibk(path)

    def test_output_is_gzipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.tachibk"
            result = self._export(path)
            self.assertTrue(result.ok, result.summary())
            self.assertEqual(path.open("rb").read(2), b"\x1f\x8b")

    def test_result_counts_match_the_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._export(Path(tmp) / "out.tachibk")
        self.assertEqual(result.exported_manga, 2)
        self.assertEqual(result.exported_chapters, 2)
        self.assertEqual(result.exported_categories, 2)
        self.assertGreater(result.bytes_written, 0)

    def test_missing_parent_directory_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "deeper" / "out.tachibk"
            result = self._export(path)
        self.assertTrue(result.ok, result.summary())

    def test_build_failure_is_reported_not_raised(self):
        class Exploding:
            def get_categories(self):
                raise RuntimeError("db is gone")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("mihon.core.tachibk_exporter.get_db", return_value=Exploding()):
                result = export_tachibk(Path(tmp) / "out.tachibk")
        self.assertFalse(result.ok)
        self.assertIn("db is gone", result.summary())

    def test_default_backup_name_is_a_tachibk(self):
        self.assertTrue(default_backup_name().endswith(".tachibk"))
        self.assertTrue(default_backup_name().startswith("mihon_"))


class RoundTripTests(unittest.TestCase):
    """Export, then read it back with the importer's own parser."""

    def test_export_then_parse_preserves_the_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roundtrip.tachibk"
            with patch("mihon.core.tachibk_exporter.get_db", return_value=_sample_db()):
                export_tachibk(path)
            restored = parse_backup(path)

        self.assertEqual([m.title for m in restored.mangas], ["One Piece", "Berserk"])
        self.assertEqual([c[0] for c in restored.categories],
                         ["Reading", "Plan to Read"])

        one_piece = restored.mangas[0]
        self.assertEqual(one_piece.author, "Eiichiro Oda")
        self.assertEqual(one_piece.genres, ["Action", "Adventure"])
        self.assertTrue(one_piece.favorite)
        self.assertEqual(one_piece.chapter_count, 2)
        self.assertEqual(one_piece.categories, [1])
        self.assertEqual(one_piece.chapters[0]["name"], "Chapter 1")
        self.assertTrue(one_piece.chapters[0]["read"])
        self.assertEqual(one_piece.chapters[0]["last_page_read"], 17)

    def test_status_survives_the_round_trip_as_a_string(self):
        """The exporter's string->int map is the exact inverse of the importer's."""
        from mihon.core.tachibk_importer import _status_to_string

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roundtrip.tachibk"
            with patch("mihon.core.tachibk_exporter.get_db", return_value=_sample_db()):
                export_tachibk(path)
            restored = parse_backup(path)

        self.assertEqual(_status_to_string(restored.mangas[0].status), "ongoing")
        self.assertEqual(_status_to_string(restored.mangas[1].status), "on hiatus")

    def test_unknown_status_round_trips_as_empty(self):
        from mihon.core.tachibk_importer import _status_to_string

        self.assertEqual(_status_to_string(0), "")

    def test_source_id_survives_the_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roundtrip.tachibk"
            with patch("mihon.core.tachibk_exporter.get_db", return_value=_sample_db()):
                export_tachibk(path)
            restored = parse_backup(path)

        self.assertEqual(restored.mangas[0].source, 2499283573021220255)
        self.assertEqual(restored.mangas[1].source,
                         tachiyomi_source_id("mangadex", "all"))


if __name__ == "__main__":
    unittest.main()


class SourceIdRoundTripTests(unittest.TestCase):
    """A backup this app writes must re-import onto the same library rows."""

    def test_builtin_source_id_maps_back_to_its_name(self):
        from mihon.core.source_ids import to_android_id, to_local_id

        for name in ["mangadex", "allmanga", "mangafire"]:
            self.assertEqual(to_local_id(to_android_id(name)), name)

    def test_unknown_numeric_id_keeps_the_mihon_prefix(self):
        from mihon.core.source_ids import to_android_id, to_local_id

        self.assertEqual(to_local_id(987654321), "mihon:987654321")
        self.assertEqual(to_android_id("mihon:987654321"), 987654321)

    def test_prefixed_id_survives_repeated_round_trips(self):
        from mihon.core.source_ids import to_android_id, to_local_id

        local = "mihon:2499283573021220255"
        for _ in range(3):
            local = to_local_id(to_android_id(local))
        self.assertEqual(local, "mihon:2499283573021220255")
