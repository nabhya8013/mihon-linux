"""
MangaDex extension for Mihon Linux.
Uses the public MangaDex API v5: https://api.mangadex.org

MangaDex is a free, open-source manga hosting service with a well-documented
REST API that requires no authentication for reading.
"""
import re
import time
import requests
from typing import List, Tuple, Optional
from .base import Extension
from ..core.models import Manga, Chapter, Page, SearchFilter, ExtensionInfo


API_BASE = "https://api.mangadex.org"
COVER_BASE = "https://uploads.mangadex.org/covers"
IMG_BASE = "https://uploads.mangadex.org"

HEADERS = {
    "User-Agent": "Mihon-Linux/1.0",
}

MANGA_INCLUDES = ["cover_art", "author", "artist"]
CHAPTER_INCLUDES = ["scanlation_group"]

ITEMS_PER_PAGE = 24


class MangaDexExtension(Extension):

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self._content_ratings = ["safe", "suggestive", "erotica"]
        self._language = "en"

    @property
    def info(self) -> ExtensionInfo:
        return ExtensionInfo(
            id="mangadex",
            name="MangaDex",
            version="1.0.0",
            language="en",
            description="MangaDex — free, community-driven manga reader",
            installed=True,
            has_settings=True,
            nsfw=False,
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get(self, path: str, params: dict = None) -> dict:
        """Make a GET request to the MangaDex API."""
        resp = self._session.get(
            f"{API_BASE}{path}",
            params=params or {},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _extract_cover_url(self, manga_id: str, relationships: list) -> str:
        """Extract cover art filename from relationships."""
        for rel in (relationships or []):
            if rel.get("type") == "cover_art":
                attrs = rel.get("attributes") or {}
                filename = attrs.get("fileName", "")
                if filename:
                    return f"{COVER_BASE}/{manga_id}/{filename}.256.jpg"
        return ""

    def _extract_author(self, relationships: list) -> str:
        """Extract author name from relationships."""
        for rel in (relationships or []):
            if rel.get("type") == "author":
                attrs = rel.get("attributes") or {}
                return attrs.get("name", "")
        return ""

    def _extract_artist(self, relationships: list) -> str:
        """Extract artist name from relationships."""
        for rel in (relationships or []):
            if rel.get("type") == "artist":
                attrs = rel.get("attributes") or {}
                return attrs.get("name", "")
        return ""

    def _get_localized(self, obj: dict, lang: str = "en") -> str:
        """Get localized string from MangaDex's {lang: text} format."""
        if not obj or not isinstance(obj, dict):
            return ""
        return obj.get(lang) or obj.get("ja-ro") or obj.get("ja") or next(iter(obj.values()), "")

    def _node_to_manga(self, item: dict) -> Manga:
        """Convert a MangaDex API manga object to our Manga model."""
        if not item:
            return Manga()

        attrs = item.get("attributes") or {}
        relationships = item.get("relationships") or []
        manga_id = item.get("id", "")

        m = Manga()
        m.source_id = self.id
        m.source_manga_id = manga_id
        m.title = self._get_localized(attrs.get("title"))

        # Alt titles
        alt_titles_raw = attrs.get("altTitles") or []
        m.alt_titles = []
        for alt in alt_titles_raw:
            if isinstance(alt, dict):
                for val in alt.values():
                    if val and val != m.title:
                        m.alt_titles.append(str(val))

        # Description
        m.description = self._get_localized(attrs.get("description"))

        # Genres / Tags
        tags = attrs.get("tags") or []
        m.genres = []
        for tag in tags:
            tag_attrs = (tag.get("attributes") or {})
            tag_name = self._get_localized(tag_attrs.get("name"))
            if tag_name:
                m.genres.append(tag_name)

        # Author / Artist
        m.author = self._extract_author(relationships)
        m.artist = self._extract_artist(relationships)

        # Status
        status_map = {
            "ongoing": "ongoing",
            "completed": "completed",
            "hiatus": "hiatus",
            "cancelled": "cancelled",
        }
        raw_status = attrs.get("status") or ""
        m.status = status_map.get(raw_status, raw_status)

        # Cover
        m.cover_url = self._extract_cover_url(manga_id, relationships)

        # URL
        m.url = f"https://mangadex.org/title/{manga_id}"

        # Year
        m.year = attrs.get("year")

        # Content rating
        m.content_rating = attrs.get("contentRating") or "safe"

        return m

    # ── Extension API ─────────────────────────────────────────────────────

    def get_popular(self, page: int = 1) -> Tuple[List[Manga], bool]:
        offset = (page - 1) * ITEMS_PER_PAGE
        try:
            data = self._get("/manga", {
                "includes[]": MANGA_INCLUDES,
                "order[followedCount]": "desc",
                "contentRating[]": self._content_ratings,
                "hasAvailableChapters": "true",
                "limit": ITEMS_PER_PAGE,
                "offset": offset,
            })
        except Exception as e:
            print(f"[mangadex] Popular error: {e}")
            return [], False

        items = data.get("data") or []
        total = (data.get("total") or 0)
        mangas = [self._node_to_manga(item) for item in items]
        has_next = (offset + ITEMS_PER_PAGE) < total
        return mangas, has_next

    def get_latest(self, page: int = 1) -> Tuple[List[Manga], bool]:
        offset = (page - 1) * ITEMS_PER_PAGE
        try:
            data = self._get("/manga", {
                "includes[]": MANGA_INCLUDES,
                "order[latestUploadedChapter]": "desc",
                "contentRating[]": self._content_ratings,
                "hasAvailableChapters": "true",
                "limit": ITEMS_PER_PAGE,
                "offset": offset,
            })
        except Exception as e:
            print(f"[mangadex] Latest error: {e}")
            return [], False

        items = data.get("data") or []
        total = (data.get("total") or 0)
        mangas = [self._node_to_manga(item) for item in items]
        has_next = (offset + ITEMS_PER_PAGE) < total
        return mangas, has_next

    def search(self, filters: SearchFilter, page: int = 1) -> Tuple[List[Manga], bool]:
        offset = (page - 1) * ITEMS_PER_PAGE
        params = {
            "includes[]": MANGA_INCLUDES,
            "contentRating[]": self._content_ratings,
            "hasAvailableChapters": "true",
            "limit": ITEMS_PER_PAGE,
            "offset": offset,
            "order[relevance]": "desc",
        }

        if filters.query:
            params["title"] = filters.query

        if filters.genres:
            # MangaDex uses tag UUIDs, but we'll support tag names via a lookup
            params["includedTags[]"] = filters.genres

        try:
            data = self._get("/manga", params)
        except Exception as e:
            print(f"[mangadex] Search error: {e}")
            return [], False

        items = data.get("data") or []
        total = (data.get("total") or 0)
        mangas = [self._node_to_manga(item) for item in items]
        has_next = (offset + ITEMS_PER_PAGE) < total
        return mangas, has_next

    def get_manga_details(self, manga: Manga) -> Manga:
        try:
            data = self._get(f"/manga/{manga.source_manga_id}", {
                "includes[]": MANGA_INCLUDES,
            })
        except Exception as e:
            print(f"[mangadex] Detail error: {e}")
            return manga

        item = data.get("data")
        if not item:
            return manga

        updated = self._node_to_manga(item)
        # Preserve library state
        updated.id = manga.id
        updated.in_library = manga.in_library
        updated.reading_status = manga.reading_status
        updated.added_at = manga.added_at
        return updated

    def get_chapters(self, manga: Manga) -> List[Chapter]:
        """Fetch all English chapters for a manga, handling pagination."""
        all_chapters = []
        offset = 0
        limit = 100

        while True:
            try:
                data = self._get(f"/manga/{manga.source_manga_id}/feed", {
                    "translatedLanguage[]": [self._language],
                    "includes[]": CHAPTER_INCLUDES,
                    "order[chapter]": "desc",
                    "limit": limit,
                    "offset": offset,
                    "contentRating[]": self._content_ratings,
                })
            except Exception as e:
                print(f"[mangadex] Chapters error: {e}")
                break

            items = data.get("data") or []
            total = data.get("total") or 0

            for item in items:
                attrs = item.get("attributes") or {}
                ch = Chapter()
                ch.manga_id = manga.id or 0
                ch.source_chapter_id = item.get("id", "")

                ch_num = attrs.get("chapter")
                try:
                    ch.chapter_number = float(ch_num) if ch_num else -1
                except (ValueError, TypeError):
                    ch.chapter_number = -1

                vol = attrs.get("volume")
                try:
                    ch.volume_number = float(vol) if vol else None
                except (ValueError, TypeError):
                    ch.volume_number = None

                ch.title = attrs.get("title") or ""
                if not ch.title and ch.chapter_number >= 0:
                    ch.title = f"Chapter {ch.chapter_number:g}"

                # Scanlator
                rels = item.get("relationships") or []
                scanlators = []
                for rel in rels:
                    if rel.get("type") == "scanlation_group":
                        grp_attrs = rel.get("attributes") or {}
                        grp_name = grp_attrs.get("name", "")
                        if grp_name:
                            scanlators.append(grp_name)
                ch.scanlator = ", ".join(scanlators) or "Unknown"

                # Dates
                published = attrs.get("publishAt") or attrs.get("createdAt") or ""
                if published:
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                        ch.uploaded_at = dt.timestamp()
                    except Exception:
                        pass

                ch.page_count = attrs.get("pages") or 0
                ch.url = item.get("id", "")
                all_chapters.append(ch)

            offset += limit
            if offset >= total or not items:
                break

        return all_chapters

    def get_pages(self, chapter: Chapter) -> List[Page]:
        """Fetch page image URLs for a chapter using the at-home API."""
        chapter_id = chapter.url  # We stored the chapter UUID in url
        if not chapter_id:
            return []

        try:
            data = self._get(f"/at-home/server/{chapter_id}")
        except Exception as e:
            print(f"[mangadex] Pages error: {e}")
            return []

        base_url = data.get("baseUrl", "")
        ch_data = data.get("chapter") or {}
        ch_hash = ch_data.get("hash", "")
        page_filenames = ch_data.get("data") or []       # Full quality
        data_saver = ch_data.get("dataSaver") or []       # Compressed

        pages = []
        for i, filename in enumerate(page_filenames):
            full_url = f"{base_url}/data/{ch_hash}/{filename}"
            saver_url = ""
            if i < len(data_saver):
                saver_url = f"{base_url}/data-saver/{ch_hash}/{data_saver[i]}"

            pages.append(Page(
                index=i,
                url=full_url,
                image_url=full_url,
            ))

        return pages

    # ── Settings ──────────────────────────────────────────────────────────

    def has_settings(self) -> bool:
        return True

    def get_settings(self) -> dict:
        return {
            "language": {
                "type": "select",
                "label": "Preferred Language",
                "options": ["en", "ja", "ko", "zh", "es", "fr", "de", "pt-br", "it"],
                "current": self._language,
            },
            "content_rating": {
                "type": "multi_select",
                "label": "Content Ratings",
                "options": ["safe", "suggestive", "erotica", "pornographic"],
                "current": self._content_ratings,
            },
        }

    def save_settings(self, settings: dict):
        if "language" in settings:
            self._language = settings["language"]
        if "content_rating" in settings:
            self._content_ratings = settings["content_rating"]
