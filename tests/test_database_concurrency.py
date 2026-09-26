"""
Tests for database thread safety.

The connection is opened with check_same_thread=False because UI work runs on
worker threads. These check that concurrent writes through it are serialised
rather than colliding.
"""
import importlib
import os
import tempfile
import threading
import unittest


def _fresh_db():
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    from mihon.core import database
    importlib.reload(database)
    return database, database.Database()


class ConcurrentWriteTests(unittest.TestCase):

    def setUp(self):
        self.database, self.db = _fresh_db()
        from mihon.core.models import Chapter, Manga
        self.Manga = Manga
        self.Chapter = Chapter

    def test_concurrent_manga_writes_all_land(self):
        errors = []

        def writer(start):
            try:
                for i in range(start, start + 25):
                    self.db.upsert_manga(self.Manga(
                        source_id="s", source_manga_id=f"m{i}", title=f"T{i}",
                        in_library=True,
                    ))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(n * 25,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(self.db.get_library()), 100)

    def test_concurrent_chapter_upserts_do_not_collide(self):
        """A chapter upsert is many statements plus a commit."""
        errors = []
        manga_ids = [
            self.db.upsert_manga(self.Manga(
                source_id="s", source_manga_id=f"m{i}", title=f"T{i}", in_library=True
            ))
            for i in range(4)
        ]

        def writer(manga_id):
            try:
                for round_number in range(5):
                    self.db.upsert_chapters([
                        self.Chapter(
                            manga_id=manga_id,
                            source_chapter_id=f"c{n}",
                            title=f"Chapter {n}",
                            chapter_number=float(n),
                            source_order=n,
                        )
                        for n in range(10)
                    ])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(mid,)) for mid in manga_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        for manga_id in manga_ids:
            self.assertEqual(len(self.db.get_chapters(manga_id)), 10)

    def test_reads_and_writes_can_interleave(self):
        errors = []
        stop = threading.Event()

        def reader():
            try:
                while not stop.is_set():
                    self.db.get_library()
            except Exception as exc:
                errors.append(exc)

        def writer():
            try:
                for i in range(50):
                    self.db.upsert_manga(self.Manga(
                        source_id="s", source_manga_id=f"m{i}", title=f"T{i}",
                        in_library=True,
                    ))
            except Exception as exc:
                errors.append(exc)
            finally:
                stop.set()

        threads = [threading.Thread(target=reader), threading.Thread(target=writer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [])

    def test_settings_writes_from_many_threads(self):
        errors = []

        def writer(name):
            try:
                for i in range(30):
                    self.db.set_setting(f"key_{name}", str(i))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        for n in range(5):
            self.assertEqual(self.db.get_setting(f"key_{n}"), "29")


class TransactionTests(unittest.TestCase):

    def setUp(self):
        self.database, self.db = _fresh_db()

    def test_the_lock_is_reentrant(self):
        """A method holding the lock must be able to call another one."""
        with self.db.transaction():
            with self.db.transaction():
                self.db.set_setting("nested", "yes")
        self.assertEqual(self.db.get_setting("nested"), "yes")

    def test_an_exception_rolls_back_and_propagates(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                self.db.conn.execute(
                    "INSERT OR REPLACE INTO settings(key, value) VALUES('rolled','1')"
                )
                raise RuntimeError("boom")
        self.assertEqual(self.db.get_setting("rolled"), "")

    def test_busy_timeout_is_configured(self):
        """Without it a locked write fails instantly instead of waiting."""
        value = self.db.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertGreater(value, 0)

    def test_wal_mode_is_on(self):
        mode = self.db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_foreign_keys_are_enforced(self):
        enabled = self.db.conn.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(enabled, 1)


class SingletonTests(unittest.TestCase):

    def test_get_db_returns_one_instance_under_a_race(self):
        database, _ = _fresh_db()
        database._db = None

        found = []
        barrier = threading.Barrier(8)

        def grab():
            barrier.wait()
            found.append(database.get_db())

        threads = [threading.Thread(target=grab) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len({id(db) for db in found}), 1)


if __name__ == "__main__":
    unittest.main()
