"""
Tests for the fetch policy and the fetch timestamps behind it.

The policy decides when the detail page goes back to a source. The point of
these tests is that a fresh copy is never refetched and a stale or missing one
always is.
"""
import importlib
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from mihon.core import fetch_policy
from mihon.core.models import Chapter, Manga

NOW = 1_000_000.0
HOUR = 3600.0


def _manga(**kw):
    fields = dict(id=1, source_id="s", source_manga_id="m", initialized=True,
                  details_fetched_at=NOW - 60, chapters_fetched_at=NOW - 60)
    fields.update(kw)
    return Manga(**fields)


class DetailsPolicyTests(unittest.TestCase):
    def test_fresh_initialized_manga_is_not_refetched(self):
        self.assertFalse(fetch_policy.needs_details(_manga(), now=NOW))

    def test_uninitialized_manga_is_fetched(self):
        self.assertTrue(fetch_policy.needs_details(_manga(initialized=False), now=NOW))

    def test_manga_without_a_row_is_fetched(self):
        self.assertTrue(fetch_policy.needs_details(_manga(id=None), now=NOW))

    def test_details_expire_after_a_day(self):
        age = fetch_policy.DETAILS_TTL_SECONDS
        self.assertFalse(fetch_policy.needs_details(_manga(details_fetched_at=NOW - age + 1), now=NOW))
        self.assertTrue(fetch_policy.needs_details(_manga(details_fetched_at=NOW - age), now=NOW))

    def test_initialized_but_never_timestamped_is_fetched(self):
        # Rows from before the timestamp column existed.
        self.assertTrue(fetch_policy.needs_details(_manga(details_fetched_at=None), now=NOW))

    def test_force_always_fetches(self):
        self.assertTrue(fetch_policy.needs_details(_manga(), now=NOW, force=True))

    def test_future_timestamp_is_not_trusted(self):
        self.assertTrue(fetch_policy.needs_details(_manga(details_fetched_at=NOW + HOUR), now=NOW))


class ChapterPolicyTests(unittest.TestCase):
    def test_fresh_list_is_not_refetched(self):
        self.assertFalse(fetch_policy.needs_chapters(_manga(), cached_count=10, now=NOW))

    def test_empty_cache_is_fetched_even_when_timestamp_is_fresh(self):
        self.assertTrue(fetch_policy.needs_chapters(_manga(), cached_count=0, now=NOW))

    def test_chapters_expire_after_an_hour(self):
        ttl = fetch_policy.CHAPTER_TTL_SECONDS
        self.assertFalse(fetch_policy.needs_chapters(
            _manga(chapters_fetched_at=NOW - ttl + 1), cached_count=3, now=NOW))
        self.assertTrue(fetch_policy.needs_chapters(
            _manga(chapters_fetched_at=NOW - ttl), cached_count=3, now=NOW))

    def test_never_timestamped_is_fetched(self):
        self.assertTrue(fetch_policy.needs_chapters(
            _manga(chapters_fetched_at=None), cached_count=3, now=NOW))

    def test_uncacheable_source_is_always_fetched(self):
        self.assertTrue(fetch_policy.needs_chapters(_manga(), cached_count=3, cacheable=False, now=NOW))

    def test_force_always_fetches(self):
        self.assertTrue(fetch_policy.needs_chapters(_manga(), cached_count=3, now=NOW, force=True))

    def test_chapters_expire_sooner_than_details(self):
        self.assertLess(fetch_policy.CHAPTER_TTL_SECONDS, fetch_policy.DETAILS_TTL_SECONDS)


def _fresh_db():
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    from mihon.core import database
    importlib.reload(database)
    return database.Database()


class TimestampStorageTests(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()
        self.manga_id = self.db.upsert_manga(Manga(source_id="s", source_manga_id="m", title="T"))

    def get(self):
        return self.db.get_manga_by_id(self.manga_id)

    def test_new_manga_has_never_been_fetched(self):
        m = self.get()
        self.assertIsNone(m.details_fetched_at)
        self.assertIsNone(m.chapters_fetched_at)

    def test_marks_are_stored_independently(self):
        self.db.mark_details_fetched(self.manga_id, 111.0)
        self.assertEqual(self.get().details_fetched_at, 111.0)
        self.assertIsNone(self.get().chapters_fetched_at)
        self.db.mark_chapters_fetched(self.manga_id, 222.0)
        self.assertEqual(self.get().chapters_fetched_at, 222.0)
        self.assertEqual(self.get().details_fetched_at, 111.0)

    def test_upsert_does_not_reset_timestamps(self):
        self.db.mark_details_fetched(self.manga_id, 111.0)
        self.db.mark_chapters_fetched(self.manga_id, 222.0)
        self.db.upsert_manga(Manga(source_id="s", source_manga_id="m", title="Changed"))
        m = self.get()
        self.assertEqual((m.details_fetched_at, m.chapters_fetched_at), (111.0, 222.0))

    def test_default_timestamp_is_now(self):
        self.db.mark_chapters_fetched(self.manga_id)
        import time
        self.assertAlmostEqual(self.get().chapters_fetched_at, time.time(), delta=5)

    def test_migration_adds_columns_to_an_old_database(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        raw = sqlite3.connect(path)
        raw.executescript("""
            CREATE TABLE manga (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
                source_manga_id TEXT NOT NULL, title TEXT NOT NULL,
                alt_titles TEXT DEFAULT '[]', author TEXT DEFAULT '', artist TEXT DEFAULT '',
                description TEXT DEFAULT '', genres TEXT DEFAULT '[]', status TEXT DEFAULT '',
                cover_url TEXT DEFAULT '', url TEXT DEFAULT '', in_library INTEGER DEFAULT 0,
                reading_status TEXT DEFAULT 'none', unread_count INTEGER DEFAULT 0,
                chapter_count INTEGER DEFAULT 0, last_read_at REAL, added_at REAL,
                updated_at REAL, cover_local_path TEXT, score REAL DEFAULT 0.0,
                year INTEGER, content_rating TEXT DEFAULT 'safe',
                UNIQUE(source_id, source_manga_id));
            INSERT INTO manga(source_id, source_manga_id, title) VALUES('s','m','Old');
        """)
        raw.commit()
        raw.close()
        from mihon.core import database
        with patch.object(database, "DB_PATH", path):
            db = database.Database()
        m = db.get_manga_by_source("s", "m")
        self.assertEqual(m.title, "Old")
        self.assertIsNone(m.chapters_fetched_at)
        db.mark_chapters_fetched(m.id, 5.0)
        self.assertEqual(db.get_manga_by_id(m.id).chapters_fetched_at, 5.0)


class SourceCachingFlagTests(unittest.TestCase):
    def test_remote_sources_cache_and_the_local_source_does_not(self):
        from mihon.extensions.base import Extension
        from mihon.extensions.local import LocalSource
        self.assertTrue(Extension.cache_chapters)
        self.assertFalse(LocalSource.cache_chapters)


if __name__ == "__main__":
    unittest.main()
