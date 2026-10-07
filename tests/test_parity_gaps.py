"""
Tests for three Android-parity gaps:

- built-in sources record the source's chapter order,
- tracker links and reading mode survive a .tachibk round trip,
- the reader remembers the reading direction per series.
"""
import gzip
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

Gtk.init_check()
Adw.init()

from mihon.core import backup_mapping as bm
from mihon.core.models import Chapter, Manga, ReadingDirection
from mihon.core.tracking.base import (
    STATUS_COMPLETED, STATUS_PLAN_TO_READ, STATUS_READING, STATUS_REREADING, TrackEntry,
)
from mihon.extensions.base import apply_source_order


def _fresh_db():
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    from mihon.core import database
    importlib.reload(database)
    return database.get_db()


def chapters(*numbers):
    return [Chapter(source_chapter_id=str(i), chapter_number=n) for i, n in enumerate(numbers)]


class SourceOrderTests(unittest.TestCase):
    def test_newest_first_list(self):
        result = apply_source_order(chapters(3.0, 2.0, 1.0))
        self.assertEqual([c.source_order for c in result], [0, 1, 2])

    def test_oldest_first_list_is_reversed(self):
        result = apply_source_order(chapters(1.0, 2.0, 3.0))
        self.assertEqual([c.source_order for c in result], [2, 1, 0])

    def test_unnumbered_chapter_keeps_its_place(self):
        # Oldest first: 1, special, 2. The special sits between 1 and 2.
        result = apply_source_order(chapters(1.0, -1.0, 2.0))
        order = {c.chapter_number: c.source_order for c in result}
        self.assertLess(order[2.0], order[-1.0])
        self.assertLess(order[-1.0], order[1.0])

    def test_no_numbers_assumes_newest_first(self):
        result = apply_source_order(chapters(-1.0, -1.0))
        self.assertEqual([c.source_order for c in result], [0, 1])

    def test_empty(self):
        self.assertEqual(apply_source_order([]), [])


class TrackerMappingTests(unittest.TestCase):
    def record(self, sync_id, status, score):
        return {"sync_id": sync_id, "media_id": 123, "library_id": 9, "title": "T",
                "last_chapter_read": 12.0, "total_chapters": 50, "score": score,
                "status": status, "url": "u", "started": 1_700_000_000_000, "finished": 0}

    def test_anilist_codes_and_100_point_score(self):
        entry = bm.tracking_from_backup(self.record(2, 5, 85.0))
        self.assertEqual(entry.provider, "anilist")
        self.assertEqual(entry.status, STATUS_PLAN_TO_READ)
        self.assertAlmostEqual(entry.score, 8.5)
        self.assertEqual(entry.remote_id, "123")
        self.assertEqual(entry.progress, 12.0)
        self.assertAlmostEqual(entry.started_at, 1_700_000_000.0)
        self.assertIsNone(entry.finished_at)

    def test_myanimelist_codes_differ_after_four(self):
        self.assertEqual(bm.tracking_from_backup(self.record(1, 6, 7.0)).status, STATUS_PLAN_TO_READ)
        self.assertEqual(bm.tracking_from_backup(self.record(1, 7, 7.0)).status, STATUS_REREADING)
        self.assertEqual(bm.tracking_from_backup(self.record(1, 2, 7.0)).status, STATUS_COMPLETED)
        self.assertAlmostEqual(bm.tracking_from_backup(self.record(1, 1, 7.0)).score, 7.0)

    def test_unsupported_tracker_is_skipped(self):
        self.assertIsNone(bm.tracking_from_backup(self.record(3, 1, 0)))  # Kitsu

    def test_round_trip(self):
        for provider in ("anilist", "myanimelist"):
            entry = TrackEntry(provider=provider, remote_id="55", library_id="8", title="X",
                               status=STATUS_REREADING, progress=4.0, score=6.5, total_chapters=10.0,
                               url="u", started_at=1_700_000_000.0, finished_at=None)
            back = bm.tracking_from_backup(bm.tracking_to_backup(entry))
            self.assertEqual((back.provider, back.status, back.remote_id, back.progress),
                             (provider, STATUS_REREADING, "55", 4.0))
            self.assertAlmostEqual(back.score, 6.5)

    def test_non_numeric_remote_id_is_not_exported(self):
        self.assertIsNone(bm.tracking_to_backup(TrackEntry(provider="anilist", remote_id="abc")))


class ViewerFlagTests(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(bm.reading_mode_from_viewer_flags(0), "")
        self.assertEqual(bm.reading_mode_from_viewer_flags(1), "ltr")
        self.assertEqual(bm.reading_mode_from_viewer_flags(2), "rtl")
        self.assertEqual(bm.reading_mode_from_viewer_flags(4), "webtoon")
        self.assertEqual(bm.reading_mode_from_viewer_flags(5), "webtoon")

    def test_orientation_bits_are_ignored_and_kept(self):
        self.assertEqual(bm.reading_mode_from_viewer_flags(0x18 | 2), "rtl")
        self.assertEqual(bm.viewer_flags_for_reading_mode("ltr", 0x18 | 2), 0x18 | 1)
        self.assertEqual(bm.viewer_flags_for_reading_mode("", 0x18 | 2), 0x18)


class BackupRoundTripTests(unittest.TestCase):
    """Export from one database, restore into a fresh one."""

    def test_tracking_and_reading_mode_survive(self):
        from mihon.core import tachibk_exporter, tachibk_importer
        db = _fresh_db()
        mid = db.upsert_manga(Manga(source_id="mihon:777", source_manga_id="/m", title="M", in_library=True))
        db.upsert_manga_tracking(mid, "anilist", status=STATUS_READING, progress=3.0, score=8.0,
                                 remote_id="100", library_id="5", title="M")
        db.upsert_manga_tracking(mid, "myanimelist", status=STATUS_COMPLETED, progress=9.0,
                                 score=7.0, remote_id="200", title="M")
        db.set_manga_reading_mode(mid, "webtoon")
        out = Path(tempfile.mkdtemp()) / "b.tachibk"
        with patch.object(tachibk_exporter, "get_db", return_value=db):
            self.assertTrue(tachibk_exporter.export_tachibk(out).ok)

        fresh = _fresh_db()
        with patch.object(tachibk_importer, "get_db", return_value=fresh):
            result = tachibk_importer.import_tachibk(out, apply=True)
        self.assertEqual(result.imported_trackers, 2, result.summary())
        new_id = fresh.get_manga_by_source("mihon:777", "/m").id
        rows = {r["provider"]: r for r in fresh.get_manga_tracking(new_id)}
        self.assertEqual(rows["anilist"]["remote_id"], "100")
        self.assertAlmostEqual(rows["anilist"]["score"], 8.0)
        self.assertEqual(rows["myanimelist"]["status"], STATUS_COMPLETED)
        self.assertEqual(fresh.get_manga_reading_mode(new_id), "webtoon")

    def test_merge_keeps_existing_link_and_mode(self):
        from mihon.core import tachibk_exporter, tachibk_importer
        db = _fresh_db()
        mid = db.upsert_manga(Manga(source_id="mihon:777", source_manga_id="/m", title="M", in_library=True))
        db.upsert_manga_tracking(mid, "anilist", status=STATUS_COMPLETED, progress=50.0, remote_id="100")
        db.set_manga_reading_mode(mid, "rtl")
        out = Path(tempfile.mkdtemp()) / "b.tachibk"
        with patch.object(tachibk_exporter, "get_db", return_value=db):
            tachibk_exporter.export_tachibk(out)
        # Local state moves on after the backup was taken.
        db.upsert_manga_tracking(mid, "anilist", status=STATUS_READING, progress=60.0, remote_id="100")
        db.set_manga_reading_mode(mid, "ltr")
        with patch.object(tachibk_importer, "get_db", return_value=db):
            tachibk_importer.import_tachibk(out, apply=True, mode=tachibk_importer.ConflictMode.MERGE)
        row = db.get_manga_tracking(mid)[0]
        self.assertEqual((row["status"], row["progress"]), (STATUS_READING, 60.0))
        self.assertEqual(db.get_manga_reading_mode(mid), "ltr")
        with patch.object(tachibk_importer, "get_db", return_value=db):
            tachibk_importer.import_tachibk(out, apply=True, mode=tachibk_importer.ConflictMode.OVERWRITE)
        row = db.get_manga_tracking(mid)[0]
        self.assertEqual((row["status"], row["progress"]), (STATUS_COMPLETED, 50.0))
        self.assertEqual(db.get_manga_reading_mode(mid), "rtl")


class PerSeriesDirectionTests(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()
        self.db.set_setting("reading_direction", "rtl")
        self.a = self.db.upsert_manga(Manga(source_id="mangadex", source_manga_id="a", title="A"))
        self.b = self.db.upsert_manga(Manga(source_id="mangadex", source_manga_id="b", title="B"))
        self.db.upsert_chapters([Chapter(manga_id=self.a, source_chapter_id="a1", chapter_number=1.0),
                                 Chapter(manga_id=self.b, source_chapter_id="b1", chapter_number=1.0)])
        from mihon.ui import reader
        with patch.object(reader, "get_db", return_value=self.db):
            self.reader = reader.ReaderView()
        self.reader._db = self.db

    def open(self, manga_id):
        manga = self.db.get_manga_by_id(manga_id)
        chapter = self.db.get_chapters(manga_id)[0]
        # Only the direction choice matters here; skip fetching pages.
        with patch("mihon.ui.reader.threading.Thread"):
            self.reader.load_chapter(manga, chapter)

    def test_default_applies_without_a_saved_mode(self):
        self.open(self.a)
        self.assertEqual(self.reader._direction, ReadingDirection.RTL)

    def test_changing_direction_saves_for_this_series_only(self):
        self.open(self.a)
        self.reader._webtoon_btn.set_active(True)
        self.assertEqual(self.db.get_manga_reading_mode(self.a), "webtoon")
        self.assertEqual(self.db.get_setting("reading_direction", ""), "rtl")
        self.open(self.b)
        self.assertEqual(self.reader._direction, ReadingDirection.RTL)
        self.open(self.a)
        self.assertEqual(self.reader._direction, ReadingDirection.WEBTOON)
        self.assertEqual(self.reader._mode, "webtoon")

    def test_use_default_clears_the_saved_mode(self):
        self.open(self.a)
        self.reader._ltr_btn.set_active(True)
        self.reader._clear_series_direction()
        self.assertEqual(self.db.get_manga_reading_mode(self.a), "")
        self.assertEqual(self.reader._direction, ReadingDirection.RTL)
        self.assertFalse(self.reader._direction_reset_btn.get_visible())


if __name__ == "__main__":
    unittest.main()
