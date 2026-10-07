"""
SQLite database layer for Mihon Linux.
Handles manga library, chapters, history, downloads, categories.
"""
import sqlite3
import json
import threading
import time
import os
from contextlib import contextmanager
from typing import Optional, List, Tuple
from pathlib import Path
from .models import (
    Manga, Chapter, Category, ReadingStatus, DownloadStatus, ReadingDirection
)


DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "mihon-linux"
DB_PATH = DATA_DIR / "library.db"
COVERS_DIR = DATA_DIR / "covers"
DOWNLOADS_DIR = DATA_DIR / "downloads"


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


class _Result:
    """
    The rows a statement produced, read while the write lock is still held.

    Returning the live cursor instead would leave the actual read happening
    after the lock is released, so another thread committing in between
    raises "bad parameter or other API misuse". Every row is materialised up
    front, which is safe here because no query in this module streams a large
    result set.
    """

    def __init__(self, cursor):
        try:
            self._rows = cursor.fetchall()
        except sqlite3.ProgrammingError:
            # Statements such as INSERT return no rows to fetch.
            self._rows = []
        self.lastrowid = cursor.lastrowid
        self.rowcount = cursor.rowcount
        self._position = 0

    def fetchone(self):
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    def fetchall(self):
        rows = self._rows[self._position:]
        self._position = len(self._rows)
        return rows

    def fetchmany(self, size=1):
        rows = self._rows[self._position:self._position + size]
        self._position += len(rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())

    def __len__(self):
        return len(self._rows)


class _LockedConnection:
    """
    A sqlite3 connection guarded by one reentrant lock.

    The connection is opened with ``check_same_thread=False`` because the UI
    runs database work on worker threads. That alone is not enough: two
    threads writing at once can raise "database is locked" or interleave a
    statement with another thread's commit. Serialising every call through a
    single lock removes that, and the lock is reentrant so a method holding
    it can still call another one.

    WAL mode keeps concurrent *readers* fast, so this costs little.
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock):
        self._conn = conn
        self._lock = lock

    def execute(self, *args, **kwargs):
        with self._lock:
            return _Result(self._conn.execute(*args, **kwargs))

    def executemany(self, *args, **kwargs):
        with self._lock:
            return _Result(self._conn.executemany(*args, **kwargs))

    def executescript(self, *args, **kwargs):
        with self._lock:
            return _Result(self._conn.executescript(*args, **kwargs))

    def commit(self):
        with self._lock:
            return self._conn.commit()

    def rollback(self):
        with self._lock:
            return self._conn.rollback()

    def cursor(self, *args, **kwargs):
        with self._lock:
            return self._conn.cursor(*args, **kwargs)

    def close(self):
        with self._lock:
            return self._conn.close()

    def __getattr__(self, name):
        # Attributes such as row_factory pass straight through.
        return getattr(self._conn, name)


class Database:
    def __init__(self):
        ensure_dirs()
        raw = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        raw.row_factory = sqlite3.Row
        self._write_lock = threading.RLock()
        self.conn = _LockedConnection(raw, self._write_lock)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        # Wait rather than fail if another process holds the write lock.
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()
        self._migrate_schema()

    @contextmanager
    def transaction(self):
        """
        Hold the write lock across several statements.

        Individual calls are already serialised, but a multi-statement write
        such as upserting a chapter list must not be interleaved with another
        thread's write and commit.
        """
        with self._write_lock:
            try:
                yield self.conn
            except Exception:
                self.conn.rollback()
                raise

    def _migrate_schema(self):
        """
        Add columns and tables introduced after the first release.

        `CREATE TABLE IF NOT EXISTS` never touches an existing table, so new
        columns need an explicit ALTER guarded by what the table already has.
        """
        c = self.conn

        tracking_columns = {
            row["name"]
            for row in c.execute("PRAGMA table_info(manga_tracking)").fetchall()
        }
        # Tracker media id and library-entry id: needed to update a remote
        # entry, and not stored by the original schema.
        for column, ddl in (
            ("remote_id", "remote_id TEXT DEFAULT ''"),
            ("library_id", "library_id TEXT DEFAULT ''"),
            ("title", "title TEXT DEFAULT ''"),
            ("total_chapters", "total_chapters REAL DEFAULT 0"),
            ("started_at", "started_at REAL"),
            ("finished_at", "finished_at REAL"),
        ):
            if column not in tracking_columns:
                c.execute(f"ALTER TABLE manga_tracking ADD COLUMN {ddl}")

        chapter_columns = {
            row["name"] for row in c.execute("PRAGMA table_info(chapters)").fetchall()
        }
        if "source_order" not in chapter_columns:
            c.execute("ALTER TABLE chapters ADD COLUMN source_order INTEGER DEFAULT 0")

        manga_columns = {
            row["name"] for row in c.execute("PRAGMA table_info(manga)").fetchall()
        }
        if "initialized" not in manga_columns:
            c.execute("ALTER TABLE manga ADD COLUMN initialized INTEGER DEFAULT 0")
        for column in ("details_fetched_at", "chapters_fetched_at"):
            if column not in manga_columns:
                c.execute(f"ALTER TABLE manga ADD COLUMN {column} REAL")
        # Reading mode chosen for this series in the reader; '' = use the default.
        if "reading_mode" not in manga_columns:
            c.execute("ALTER TABLE manga ADD COLUMN reading_mode TEXT DEFAULT ''")

        c.executescript("""
        -- Pending tracker updates that could not be delivered. Drained on the
        -- next app start and whenever a sync succeeds.
        CREATE TABLE IF NOT EXISTS tracking_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            payload TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            last_error TEXT DEFAULT '',
            queued_at REAL NOT NULL,
            next_attempt_at REAL DEFAULT 0,
            FOREIGN KEY(manga_id) REFERENCES manga(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_tracking_queue_ready
            ON tracking_queue(next_attempt_at);
        """)
        c.commit()

    def _create_tables(self):
        c = self.conn
        c.executescript("""
        CREATE TABLE IF NOT EXISTS manga (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            source_manga_id TEXT NOT NULL,
            title TEXT NOT NULL,
            alt_titles TEXT DEFAULT '[]',
            author TEXT DEFAULT '',
            artist TEXT DEFAULT '',
            description TEXT DEFAULT '',
            genres TEXT DEFAULT '[]',
            status TEXT DEFAULT '',
            cover_url TEXT DEFAULT '',
            url TEXT DEFAULT '',
            in_library INTEGER DEFAULT 0,
            reading_status TEXT DEFAULT 'none',
            unread_count INTEGER DEFAULT 0,
            chapter_count INTEGER DEFAULT 0,
            last_read_at REAL,
            added_at REAL,
            updated_at REAL,
            cover_local_path TEXT,
            score REAL DEFAULT 0.0,
            year INTEGER,
            content_rating TEXT DEFAULT 'safe',
            UNIQUE(source_id, source_manga_id)
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL,
            source_chapter_id TEXT NOT NULL,
            title TEXT DEFAULT '',
            chapter_number REAL DEFAULT -1,
            volume_number REAL,
            scanlator TEXT DEFAULT '',
            uploaded_at REAL,
            fetched_at REAL,
            read INTEGER DEFAULT 0,
            last_page_read INTEGER DEFAULT 0,
            page_count INTEGER DEFAULT 0,
            download_status TEXT DEFAULT 'not_downloaded',
            local_path TEXT,
            url TEXT DEFAULT '',
            UNIQUE(manga_id, source_chapter_id),
            FOREIGN KEY(manga_id) REFERENCES manga(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS manga_categories (
            manga_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            PRIMARY KEY(manga_id, category_id),
            FOREIGN KEY(manga_id) REFERENCES manga(id) ON DELETE CASCADE,
            FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL,
            chapter_id INTEGER NOT NULL,
            page INTEGER DEFAULT 0,
            read_at REAL NOT NULL,
            FOREIGN KEY(manga_id) REFERENCES manga(id) ON DELETE CASCADE,
            FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS manga_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            status TEXT DEFAULT '',
            progress REAL DEFAULT 0,
            score REAL DEFAULT 0,
            url TEXT DEFAULT '',
            note TEXT DEFAULT '',
            last_synced_at REAL,
            UNIQUE(manga_id, provider),
            FOREIGN KEY(manga_id) REFERENCES manga(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_manga_library ON manga(in_library);
        CREATE INDEX IF NOT EXISTS idx_chapters_manga ON chapters(manga_id);
        CREATE INDEX IF NOT EXISTS idx_history_manga ON history(manga_id);
        CREATE INDEX IF NOT EXISTS idx_tracking_manga ON manga_tracking(manga_id);
        """)
        c.commit()

        # Insert default settings
        defaults = {
            "reading_direction": ReadingDirection.RTL.value,
            "reader_background": "black",
            "page_layout": "single",
            "scale_type": "fit_page",
            "crop_borders": "0",
            "auto_update_library": "1",
            "show_unread_badge": "1",
            "library_update_interval_hours": "12",
            "smart_update_skip_dropped": "1",
            "desktop_notifications_enabled": "1",
            "smart_update_excluded_categories": "[]",
            "appearance_theme": "dark",
            "extension_language_filter": json.dumps(["en"]),
            "reader_tap_invert": "0",
            "reader_fullscreen": "0",
            "reader_keep_screen_on": "0",
            "reader_show_slider": "1",
            "reader_zoom": "1.0",
            "download_dir": str(DOWNLOADS_DIR),
            "max_simultaneous_downloads": "3",
            "tracker_anilist_token": "",
            "tracker_mal_token": "",
            "library_prefs_global": json.dumps({
                "sort_by": "title",
                "sort_desc": False,
                "display_mode": "grid",
                "status_filters": [],
                "unread_only": False,
                "downloaded_only": False,
            }),
        }
        for key, value in defaults.items():
            c.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                (key, value)
            )
        c.commit()

    # ── Manga ──────────────────────────────────────────────────────────────

    def upsert_manga(self, manga: Manga) -> int:
        """Insert or update manga, return its database ID."""
        # The write and the id lookup have to be one unit: another thread
        # could otherwise commit between them.
        with self.transaction():
            self._upsert_manga_locked(manga)
            self.conn.commit()
            row = self.conn.execute(
                "SELECT id FROM manga WHERE source_id=? AND source_manga_id=?",
                (manga.source_id, manga.source_manga_id)
            ).fetchone()
            return row["id"]

    def _upsert_manga_locked(self, manga: Manga) -> None:
        now = time.time()
        self.conn.execute("""
            INSERT INTO manga (
                source_id, source_manga_id, title, alt_titles, author, artist,
                description, genres, status, cover_url, url, in_library,
                reading_status, added_at, updated_at, cover_local_path,
                score, year, content_rating, initialized
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id, source_manga_id) DO UPDATE SET
                title=excluded.title,
                alt_titles=excluded.alt_titles,
                author=excluded.author,
                artist=excluded.artist,
                description=excluded.description,
                genres=excluded.genres,
                status=excluded.status,
                cover_url=excluded.cover_url,
                url=excluded.url,
                updated_at=excluded.updated_at,
                score=excluded.score,
                year=excluded.year,
                content_rating=excluded.content_rating,
                -- Never downgrade a fully fetched manga back to uninitialized:
                -- a later browse listing carries less than the details call did.
                initialized=MAX(manga.initialized, excluded.initialized)
        """, (
            manga.source_id, manga.source_manga_id, manga.title,
            json.dumps(manga.alt_titles), manga.author, manga.artist,
            manga.description, json.dumps(manga.genres), manga.status,
            manga.cover_url, manga.url, int(manga.in_library),
            manga.reading_status.value,
            manga.added_at or now, now,
            manga.cover_local_path, manga.score, manga.year, manga.content_rating,
            int(manga.initialized),
        ))

    def get_manga_reading_mode(self, manga_id: int) -> str:
        """The reading mode saved for one series, or '' to use the default."""
        row = self.conn.execute(
            "SELECT reading_mode FROM manga WHERE id=?", (manga_id,)
        ).fetchone()
        return (row["reading_mode"] or "") if row else ""

    def set_manga_reading_mode(self, manga_id: int, mode: str) -> None:
        self.conn.execute(
            "UPDATE manga SET reading_mode=? WHERE id=?", (mode or "", manga_id)
        )
        self.conn.commit()

    def mark_details_fetched(self, manga_id: int, when: Optional[float] = None) -> None:
        self.conn.execute(
            "UPDATE manga SET details_fetched_at=? WHERE id=?",
            (when if when is not None else time.time(), manga_id),
        )
        self.conn.commit()

    def mark_chapters_fetched(self, manga_id: int, when: Optional[float] = None) -> None:
        self.conn.execute(
            "UPDATE manga SET chapters_fetched_at=? WHERE id=?",
            (when if when is not None else time.time(), manga_id),
        )
        self.conn.commit()

    def get_manga_by_id(self, manga_id: int) -> Optional[Manga]:
        row = self.conn.execute("SELECT * FROM manga WHERE id=?", (manga_id,)).fetchone()
        return self._row_to_manga(row) if row else None

    def get_manga_by_source(self, source_id: str, source_manga_id: str) -> Optional[Manga]:
        row = self.conn.execute(
            "SELECT * FROM manga WHERE source_id=? AND source_manga_id=?",
            (source_id, source_manga_id)
        ).fetchone()
        return self._row_to_manga(row) if row else None

    def get_library(self, category_id: Optional[int] = None) -> List[Manga]:
        if category_id is not None:
            rows = self.conn.execute("""
                SELECT m.* FROM manga m
                JOIN manga_categories mc ON m.id = mc.manga_id
                WHERE m.in_library=1 AND mc.category_id=?
                ORDER BY m.title
            """, (category_id,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM manga WHERE in_library=1 ORDER BY title"
            ).fetchall()
        return [self._row_to_manga(r) for r in rows]

    def add_to_library(self, manga_id: int):
        self.conn.execute(
            "UPDATE manga SET in_library=1, added_at=? WHERE id=?",
            (time.time(), manga_id)
        )
        self.conn.commit()

    def remove_from_library(self, manga_id: int):
        self.conn.execute(
            "UPDATE manga SET in_library=0, reading_status='none' WHERE id=?",
            (manga_id,)
        )
        self.conn.commit()

    def remove_from_library_bulk(self, manga_ids: List[int]) -> int:
        if not manga_ids:
            return 0
        placeholders = ",".join("?" for _ in manga_ids)
        cur = self.conn.execute(
            f"UPDATE manga SET in_library=0, reading_status='none' WHERE id IN ({placeholders})",
            tuple(manga_ids),
        )
        self.conn.commit()
        return cur.rowcount

    def update_reading_status(self, manga_id: int, status: ReadingStatus):
        self.conn.execute(
            "UPDATE manga SET reading_status=? WHERE id=?",
            (status.value, manga_id)
        )
        self.conn.commit()

    def update_cover_path(self, manga_id: int, path: str):
        self.conn.execute(
            "UPDATE manga SET cover_local_path=? WHERE id=?",
            (path, manga_id)
        )
        self.conn.commit()

    def update_unread_count(self, manga_id: int):
        count = self.conn.execute(
            "SELECT COUNT(*) as c FROM chapters WHERE manga_id=? AND read=0",
            (manga_id,)
        ).fetchone()["c"]
        self.conn.execute(
            "UPDATE manga SET unread_count=? WHERE id=?",
            (count, manga_id)
        )
        self.conn.commit()

    def _row_to_manga(self, row) -> Manga:
        m = Manga()
        m.id = row["id"]
        m.source_id = row["source_id"]
        m.source_manga_id = row["source_manga_id"]
        m.title = row["title"]
        m.alt_titles = json.loads(row["alt_titles"] or "[]")
        m.author = row["author"] or ""
        m.artist = row["artist"] or ""
        m.description = row["description"] or ""
        m.genres = json.loads(row["genres"] or "[]")
        m.status = row["status"] or ""
        m.cover_url = row["cover_url"] or ""
        m.url = row["url"] or ""
        m.in_library = bool(row["in_library"])
        m.initialized = bool(row["initialized"])
        m.details_fetched_at = row["details_fetched_at"]
        m.chapters_fetched_at = row["chapters_fetched_at"]
        m.reading_status = ReadingStatus(row["reading_status"] or "none")
        m.unread_count = row["unread_count"] or 0
        m.chapter_count = row["chapter_count"] or 0
        m.last_read_at = row["last_read_at"]
        m.added_at = row["added_at"]
        m.updated_at = row["updated_at"]
        m.cover_local_path = row["cover_local_path"]
        m.score = row["score"] or 0.0
        m.year = row["year"]
        m.content_rating = row["content_rating"] or "safe"
        return m

    # ── Chapters ───────────────────────────────────────────────────────────

    def upsert_chapters(self, chapters: List[Chapter]) -> None:
        now = time.time()
        with self.transaction():
            self._upsert_chapters_locked(chapters, now)

    def _upsert_chapters_locked(self, chapters: List[Chapter], now: float) -> None:
        for ch in chapters:
            self.conn.execute("""
                INSERT INTO chapters (
                    manga_id, source_chapter_id, title, chapter_number,
                    volume_number, scanlator, uploaded_at, fetched_at,
                    read, last_page_read, page_count, url, source_order
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(manga_id, source_chapter_id) DO UPDATE SET
                    title=excluded.title,
                    chapter_number=excluded.chapter_number,
                    volume_number=excluded.volume_number,
                    scanlator=excluded.scanlator,
                    uploaded_at=excluded.uploaded_at,
                    fetched_at=excluded.fetched_at,
                    url=excluded.url,
                    source_order=excluded.source_order
            """, (
                ch.manga_id, ch.source_chapter_id, ch.title,
                ch.chapter_number, ch.volume_number, ch.scanlator,
                ch.uploaded_at, now,
                int(ch.read), ch.last_page_read, ch.page_count, ch.url,
                ch.source_order,
            ))
        # Update chapter count on manga
        if chapters:
            manga_id = chapters[0].manga_id
            count = self.conn.execute(
                "SELECT COUNT(*) as c FROM chapters WHERE manga_id=?", (manga_id,)
            ).fetchone()["c"]
            self.conn.execute(
                "UPDATE manga SET chapter_count=? WHERE id=?", (count, manga_id)
            )
        self.conn.commit()

    # How a manga's chapters are ordered when read back.
    CHAPTER_SORTS = {
        # Highest chapter number first. Useless on sources whose chapters have
        # no numbering, which is why source order exists.
        "number": "chapter_number DESC, source_order ASC",
        # The order the source itself listed them, newest first.
        "source": "source_order ASC, chapter_number DESC",
        "upload": "uploaded_at DESC, chapter_number DESC",
    }

    def get_chapters(self, manga_id: int, sort: str = "number") -> List[Chapter]:
        order = self.CHAPTER_SORTS.get(sort, self.CHAPTER_SORTS["number"])
        rows = self.conn.execute(
            f"SELECT * FROM chapters WHERE manga_id=? ORDER BY {order}",
            (manga_id,)
        ).fetchall()
        return [self._row_to_chapter(r) for r in rows]

    def get_chapter_by_id(self, chapter_id: int) -> Optional[Chapter]:
        row = self.conn.execute(
            "SELECT * FROM chapters WHERE id=?", (chapter_id,)
        ).fetchone()
        return self._row_to_chapter(row) if row else None

    def mark_chapter_read(self, chapter_id: int, page: int = 0):
        self.conn.execute(
            "UPDATE chapters SET read=1, last_page_read=? WHERE id=?",
            (page, chapter_id)
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT manga_id FROM chapters WHERE id=?", (chapter_id,)
        ).fetchone()
        if row:
            self.update_unread_count(row["manga_id"])

    def mark_chapter_unread(self, chapter_id: int):
        self.conn.execute(
            "UPDATE chapters SET read=0, last_page_read=0 WHERE id=?",
            (chapter_id,)
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT manga_id FROM chapters WHERE id=?", (chapter_id,)
        ).fetchone()
        if row:
            self.update_unread_count(row["manga_id"])

    def update_chapter_progress(self, chapter_id: int, page: int):
        self.conn.execute(
            "UPDATE chapters SET last_page_read=? WHERE id=?",
            (page, chapter_id)
        )
        self.conn.commit()

    def restore_chapter_progress(self, manga_id: int, progress: dict) -> None:
        """
        Set read state for several chapters of one manga at once.

        ``progress`` maps ``source_chapter_id`` to ``(read, last_page_read)``.
        `upsert_chapters` deliberately leaves read state alone on conflict, so a
        backup restore needs its own write path for chapters already stored.
        """
        if not progress:
            return
        with self.transaction():
            for source_chapter_id, (read, page) in progress.items():
                self.conn.execute(
                    "UPDATE chapters SET read=?, last_page_read=? "
                    "WHERE manga_id=? AND source_chapter_id=?",
                    (int(bool(read)), int(page or 0), manga_id, source_chapter_id),
                )
            self.conn.commit()
        self.update_unread_count(manga_id)

    def restore_history_entry(self, manga_id: int, chapter_id: int, page: int, read_at: float) -> bool:
        """
        Insert a history row with a past timestamp, unless the chapter has one.

        Returns True when a row was written. `last_read_at` only ever moves
        forward, so restoring an old backup cannot make a manga look less
        recently read than it already is.
        """
        with self.transaction():
            exists = self.conn.execute(
                "SELECT 1 FROM history WHERE manga_id=? AND chapter_id=?",
                (manga_id, chapter_id),
            ).fetchone()
            if exists:
                return False
            self.conn.execute(
                "INSERT INTO history(manga_id, chapter_id, page, read_at) VALUES(?,?,?,?)",
                (manga_id, chapter_id, page, read_at),
            )
            self.conn.execute(
                "UPDATE manga SET last_read_at=? WHERE id=? "
                "AND (last_read_at IS NULL OR last_read_at < ?)",
                (read_at, manga_id, read_at),
            )
            self.conn.commit()
            return True

    def update_download_status(self, chapter_id: int, status: DownloadStatus, local_path: str = None):
        if local_path:
            self.conn.execute(
                "UPDATE chapters SET download_status=?, local_path=? WHERE id=?",
                (status.value, local_path, chapter_id)
            )
        else:
            self.conn.execute(
                "UPDATE chapters SET download_status=? WHERE id=?",
                (status.value, chapter_id)
            )
        self.conn.commit()

    def clear_chapter_download(self, chapter_id: int):
        self.conn.execute(
            "UPDATE chapters SET download_status=?, local_path=NULL WHERE id=?",
            (DownloadStatus.NOT_DOWNLOADED.value, chapter_id),
        )
        self.conn.commit()

    def get_downloaded_manga_ids(self, manga_ids: List[int]) -> set[int]:
        if not manga_ids:
            return set()
        placeholders = ",".join("?" for _ in manga_ids)
        rows = self.conn.execute(
            f"""
            SELECT DISTINCT manga_id
            FROM chapters
            WHERE manga_id IN ({placeholders})
              AND (
                    download_status=?
                    OR (local_path IS NOT NULL AND local_path!='')
                  )
            """,
            tuple(manga_ids) + (DownloadStatus.DOWNLOADED.value,),
        ).fetchall()
        return {r["manga_id"] for r in rows}

    def mark_manga_chapters_read_bulk(self, manga_ids: List[int]) -> int:
        if not manga_ids:
            return 0
        placeholders = ",".join("?" for _ in manga_ids)
        cur = self.conn.execute(
            f"UPDATE chapters SET read=1 WHERE manga_id IN ({placeholders}) AND read=0",
            tuple(manga_ids),
        )
        self.conn.execute(
            f"UPDATE manga SET unread_count=0 WHERE id IN ({placeholders})",
            tuple(manga_ids),
        )
        self.conn.commit()
        return cur.rowcount

    def _row_to_chapter(self, row) -> Chapter:
        ch = Chapter()
        ch.id = row["id"]
        ch.manga_id = row["manga_id"]
        ch.source_chapter_id = row["source_chapter_id"]
        ch.title = row["title"] or ""
        ch.chapter_number = row["chapter_number"] or -1
        ch.volume_number = row["volume_number"]
        ch.scanlator = row["scanlator"] or ""
        ch.uploaded_at = row["uploaded_at"]
        ch.fetched_at = row["fetched_at"]
        ch.read = bool(row["read"])
        ch.last_page_read = row["last_page_read"] or 0
        ch.page_count = row["page_count"] or 0
        ch.source_order = row["source_order"] or 0
        ch.download_status = DownloadStatus(row["download_status"] or "not_downloaded")
        ch.local_path = row["local_path"]
        ch.url = row["url"] or ""
        return ch

    # ── Categories ─────────────────────────────────────────────────────────

    def get_categories(self) -> List[Category]:
        rows = self.conn.execute(
            "SELECT * FROM categories ORDER BY sort_order, name"
        ).fetchall()
        return [Category(id=r["id"], name=r["name"], sort_order=r["sort_order"]) for r in rows]

    def create_category(self, name: str) -> int:
        self.conn.execute(
            "INSERT INTO categories(name, sort_order) VALUES(?, ?)",
            (name, 0)
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM categories WHERE name=?", (name,)
        ).fetchone()
        return row["id"]

    def update_category_name(self, category_id: int, name: str):
        self.conn.execute(
            "UPDATE categories SET name=? WHERE id=?",
            (name, category_id),
        )
        self.conn.commit()

    def reorder_categories(self, ordered_category_ids: List[int]):
        for idx, category_id in enumerate(ordered_category_ids):
            self.conn.execute(
                "UPDATE categories SET sort_order=? WHERE id=?",
                (idx, category_id),
            )
        self.conn.commit()

    def delete_category(self, category_id: int):
        self.conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
        self.conn.commit()

    def set_manga_categories(self, manga_id: int, category_ids: List[int]):
        self.conn.execute(
            "DELETE FROM manga_categories WHERE manga_id=?", (manga_id,)
        )
        for cat_id in category_ids:
            self.conn.execute(
                "INSERT OR IGNORE INTO manga_categories(manga_id, category_id) VALUES(?,?)",
                (manga_id, cat_id)
            )
        self.conn.commit()

    def get_manga_category_ids(self, manga_id: int) -> List[int]:
        rows = self.conn.execute(
            "SELECT category_id FROM manga_categories WHERE manga_id=? ORDER BY category_id",
            (manga_id,),
        ).fetchall()
        return [r["category_id"] for r in rows]

    def copy_manga_categories(self, source_manga_id: int, target_manga_id: int):
        category_ids = self.get_manga_category_ids(source_manga_id)
        if category_ids:
            self.set_manga_categories(target_manga_id, category_ids)

    def add_manga_to_category_bulk(self, manga_ids: List[int], category_id: int) -> int:
        if not manga_ids:
            return 0
        cur = self.conn.cursor()
        before = self.conn.total_changes
        for manga_id in manga_ids:
            cur.execute(
                "INSERT OR IGNORE INTO manga_categories(manga_id, category_id) VALUES(?,?)",
                (manga_id, category_id),
            )
        self.conn.commit()
        return self.conn.total_changes - before

    def remove_manga_from_category_bulk(self, manga_ids: List[int], category_id: int) -> int:
        if not manga_ids:
            return 0
        placeholders = ",".join("?" for _ in manga_ids)
        cur = self.conn.execute(
            f"DELETE FROM manga_categories WHERE category_id=? AND manga_id IN ({placeholders})",
            (category_id, *manga_ids),
        )
        self.conn.commit()
        return cur.rowcount

    # ── Tracking ───────────────────────────────────────────────────────────

    def get_tracked_library_manga_ids(self) -> List[int]:
        """Library manga linked to at least one tracker."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT t.manga_id FROM manga_tracking t
            JOIN manga m ON m.id = t.manga_id
            WHERE m.in_library = 1
            ORDER BY t.manga_id
            """
        ).fetchall()
        return [r["manga_id"] for r in rows]

    def get_manga_tracking(self, manga_id: int) -> List[dict]:
        rows = self.conn.execute(
            """
            SELECT provider, status, progress, score, url, note, last_synced_at,
                   remote_id, library_id, title, total_chapters,
                   started_at, finished_at
            FROM manga_tracking
            WHERE manga_id=?
            ORDER BY provider
            """,
            (manga_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_manga_tracking(
        self,
        manga_id: int,
        provider: str,
        status: str = "",
        progress: float = 0.0,
        score: float = 0.0,
        url: str = "",
        note: str = "",
        remote_id: str = "",
        library_id: str = "",
        title: str = "",
        total_chapters: float = 0.0,
        started_at: Optional[float] = None,
        finished_at: Optional[float] = None,
    ):
        self.conn.execute(
            """
            INSERT INTO manga_tracking(
                manga_id, provider, status, progress, score, url, note,
                last_synced_at, remote_id, library_id, title, total_chapters,
                started_at, finished_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(manga_id, provider) DO UPDATE SET
                status=excluded.status,
                progress=excluded.progress,
                score=excluded.score,
                url=excluded.url,
                note=excluded.note,
                last_synced_at=excluded.last_synced_at,
                remote_id=excluded.remote_id,
                library_id=excluded.library_id,
                title=excluded.title,
                total_chapters=excluded.total_chapters,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at
            """,
            (
                manga_id, provider, status, progress, score, url, note,
                time.time(), remote_id, library_id, title, total_chapters,
                started_at, finished_at,
            ),
        )
        self.conn.commit()

    def remove_manga_tracking(self, manga_id: int, provider: str):
        self.conn.execute(
            "DELETE FROM manga_tracking WHERE manga_id=? AND provider=?",
            (manga_id, provider),
        )
        self.conn.commit()

    def copy_chapter_progress_by_number(self, source_manga_id: int, target_manga_id: int):
        source_rows = self.conn.execute(
            """
            SELECT chapter_number, read, last_page_read
            FROM chapters
            WHERE manga_id=?
            """,
            (source_manga_id,),
        ).fetchall()
        if not source_rows:
            return
        source_map = {r["chapter_number"]: (r["read"], r["last_page_read"] or 0) for r in source_rows}

        target_rows = self.conn.execute(
            """
            SELECT id, chapter_number
            FROM chapters
            WHERE manga_id=?
            """,
            (target_manga_id,),
        ).fetchall()
        for row in target_rows:
            chapter_number = row["chapter_number"]
            if chapter_number not in source_map:
                continue
            read, last_page_read = source_map[chapter_number]
            self.conn.execute(
                "UPDATE chapters SET read=?, last_page_read=? WHERE id=?",
                (read, last_page_read, row["id"]),
            )
        self.conn.commit()
        self.update_unread_count(target_manga_id)

    # ── History ────────────────────────────────────────────────────────────

    def record_history(self, manga_id: int, chapter_id: int, page: int):
        self.conn.execute("""
            INSERT INTO history(manga_id, chapter_id, page, read_at)
            VALUES(?,?,?,?)
        """, (manga_id, chapter_id, page, time.time()))
        self.conn.execute(
            "UPDATE manga SET last_read_at=? WHERE id=?",
            (time.time(), manga_id)
        )
        self.conn.commit()

    def get_history(self, limit: int = 50) -> List[dict]:
        rows = self.conn.execute("""
            SELECT h.*, m.title as manga_title, m.cover_local_path,
                   c.title as chapter_title, c.chapter_number
            FROM history h
            JOIN manga m ON h.manga_id = m.id
            JOIN chapters c ON h.chapter_id = c.id
            ORDER BY h.read_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def delete_history_item(self, history_id: int):
        self.conn.execute("DELETE FROM history WHERE id=?", (history_id,))
        self.conn.commit()

    # ── Settings ───────────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


# Singleton
_db: Optional[Database] = None

_db_lock = threading.Lock()


def get_db() -> Database:
    global _db
    # Guarded: the UI opens the database from whichever thread gets there
    # first, and two of them racing would build two connections.
    with _db_lock:
        if _db is None:
            _db = Database()
        return _db
