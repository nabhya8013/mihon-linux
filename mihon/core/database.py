"""
SQLite database layer for Mihon Linux.
Handles manga library, chapters, history, downloads, categories.
"""
import sqlite3
import json
import time
import os
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


class Database:
    def __init__(self):
        ensure_dirs()
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

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

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_manga_library ON manga(in_library);
        CREATE INDEX IF NOT EXISTS idx_chapters_manga ON chapters(manga_id);
        CREATE INDEX IF NOT EXISTS idx_history_manga ON history(manga_id);
        """)
        c.commit()

        # Insert default settings
        defaults = {
            "reading_direction": ReadingDirection.RTL.value,
            "reader_background": "black",
            "page_layout": "single",
            "scale_type": "fit_page",
            "crop_borders": "0",
            "download_dir": str(DOWNLOADS_DIR),
            "max_simultaneous_downloads": "3",
            "tracker_anilist_token": "",
            "tracker_mal_token": "",
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
        now = time.time()
        self.conn.execute("""
            INSERT INTO manga (
                source_id, source_manga_id, title, alt_titles, author, artist,
                description, genres, status, cover_url, url, in_library,
                reading_status, added_at, updated_at, cover_local_path,
                score, year, content_rating
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                content_rating=excluded.content_rating
        """, (
            manga.source_id, manga.source_manga_id, manga.title,
            json.dumps(manga.alt_titles), manga.author, manga.artist,
            manga.description, json.dumps(manga.genres), manga.status,
            manga.cover_url, manga.url, int(manga.in_library),
            manga.reading_status.value,
            manga.added_at or now, now,
            manga.cover_local_path, manga.score, manga.year, manga.content_rating
        ))
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM manga WHERE source_id=? AND source_manga_id=?",
            (manga.source_id, manga.source_manga_id)
        ).fetchone()
        return row["id"]

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
        for ch in chapters:
            self.conn.execute("""
                INSERT INTO chapters (
                    manga_id, source_chapter_id, title, chapter_number,
                    volume_number, scanlator, uploaded_at, fetched_at,
                    read, last_page_read, page_count, url
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(manga_id, source_chapter_id) DO UPDATE SET
                    title=excluded.title,
                    chapter_number=excluded.chapter_number,
                    volume_number=excluded.volume_number,
                    scanlator=excluded.scanlator,
                    uploaded_at=excluded.uploaded_at,
                    fetched_at=excluded.fetched_at,
                    url=excluded.url
            """, (
                ch.manga_id, ch.source_chapter_id, ch.title,
                ch.chapter_number, ch.volume_number, ch.scanlator,
                ch.uploaded_at, now,
                int(ch.read), ch.last_page_read, ch.page_count, ch.url
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

    def get_chapters(self, manga_id: int) -> List[Chapter]:
        rows = self.conn.execute(
            "SELECT * FROM chapters WHERE manga_id=? ORDER BY chapter_number DESC",
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

def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
