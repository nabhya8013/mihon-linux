"""
AllManga (allmanga.to / allanime.day) extension for Mihon Linux.
Uses AllAnime's GraphQL API with verified working queries.

CDN base: https://aln.youtube-anime.com/ (thumbnails and pages)
API: https://api.allanime.day/api (GraphQL, POST or GET)
"""
import re
import requests
from typing import List, Tuple, Optional
from .base import Extension
from ..core.models import Manga, Chapter, Page, SearchFilter, ExtensionInfo


API_URL = "https://api.allanime.day/api"
CDN_URL = "https://aln.youtube-anime.com/"
SITE_URL = "https://allmanga.to"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Referer": SITE_URL,
    "Origin": SITE_URL,
    "Content-Type": "application/json",
}

# ── Queries ────────────────────────────────────────────────────────────────

MANGA_FIELDS = """
    _id
    name
    englishName
    nativeName
    altNames
    thumbnail
    description
    status
    genres
    authors
    score
    rating
    airedStart
    availableChaptersDetail
    countryOfOrigin
"""

SEARCH_QUERY = """
query($search: SearchInput, $limit: Int, $page: Int) {
    mangas(search: $search, limit: $limit, page: $page) {
        edges {
            _id
            name
            englishName
            thumbnail
            score
            status
            genres
        }
        pageInfo { total limit page }
    }
}
"""

MANGA_DETAIL_QUERY = """
query($id: String!) {
    manga(_id: $id) {
        _id
        name
        englishName
        nativeName
        altNames
        thumbnail
        description
        status
        genres
        authors
        score
        rating
        airedStart
        availableChaptersDetail
        countryOfOrigin
    }
}
"""

CHAPTER_PAGES_QUERY = """
query($mangaId: String!, $translationType: VaildTranslationTypeMangaEnumType!, $chapterString: String!) {
    chapterPages(mangaId: $mangaId, translationType: $translationType, chapterString: $chapterString) {
        edges {
            _id
            chapterString
            pictureUrls
            pictureUrlHead
        }
    }
}
"""


class AllMangaExtension(Extension):

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self._translation_type = "sub"  # sub or raw

    @property
    def info(self) -> ExtensionInfo:
        return ExtensionInfo(
            id="allmanga",
            name="AllManga",
            version="1.1.0",
            language="en",
            description="AllManga.to — large manga library with sub and raw translations",
            installed=True,
            has_settings=True,
            nsfw=False,
        )

    # ── Internal ───────────────────────────────────────────────────────────

    def _gql(self, query: str, variables: dict) -> dict:
        resp = self._session.post(
            API_URL,
            json={"query": query, "variables": variables},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data and "data" not in data:
            raise Exception(f"GraphQL error: {data['errors'][0].get('message', 'unknown')}")
        return data.get("data") or {}

    def _resolve_thumbnail(self, path: str) -> str:
        """Convert relative thumbnail path to absolute CDN URL."""
        if not path:
            return ""
        if path.startswith("http"):
            return path
        return CDN_URL + path

    def _resolve_page_url(self, url: str, url_head: str = "") -> str:
        """Convert relative page image path to absolute URL."""
        if not url:
            return ""
        if url.startswith("http"):
            return url
        # Use the pictureUrlHead from API (e.g. https://aln.youtube-anime.com/)
        base = url_head or CDN_URL
        if not base.endswith("/"):
            base += "/"
        return base + url

    def _node_to_manga(self, node: dict) -> Manga:
        if not node:
            return Manga()
        m = Manga()
        m.source_id = self.id
        m.source_manga_id = str(node.get("_id", ""))
        m.title = str(node.get("englishName") or node.get("name") or "")
        
        alt_names_raw = node.get("altNames") or []
        if not isinstance(alt_names_raw, list):
            alt_names_raw = [str(alt_names_raw)]
            
        m.alt_titles = list(filter(None, [
            str(node.get("nativeName") or ""),
            str(node.get("name") or "") if node.get("englishName") else "",
        ] + [str(a) for a in alt_names_raw if a]))
        
        m.description = self._clean_html(str(node.get("description") or ""))
        
        genres_raw = node.get("genres") or []
        m.genres = [str(g) for g in genres_raw if g] if isinstance(genres_raw, list) else [str(genres_raw)]
        
        authors_raw = node.get("authors") or []
        if not isinstance(authors_raw, list):
            authors_raw = [str(authors_raw)]
        m.author = ", ".join(str(a) for a in authors_raw if a)
        m.artist = m.author

        status_map = {
            "Releasing": "ongoing",
            "Finished": "completed",
            "Hiatus": "hiatus",
            "Discontinued": "cancelled",
            "Not Yet Released": "upcoming",
        }
        raw_status = str(node.get("status") or "")
        m.status = status_map.get(raw_status, raw_status.lower())

        m.cover_url = self._resolve_thumbnail(str(node.get("thumbnail") or ""))
        m.url = f"{SITE_URL}/manga/{m.source_manga_id}"
        
        try:
            m.score = float(node.get("score") or 0)
        except (ValueError, TypeError):
            m.score = 0.0

        # Extract year from airedStart (Object: {year, month, date})
        aired = node.get("airedStart")
        if isinstance(aired, dict):
            try:
                m.year = int(aired.get("year") or 0) or None
            except (ValueError, TypeError):
                m.year = None

        m.content_rating = "safe"
        return m

    @staticmethod
    def _clean_html(text: str) -> str:
        """Remove HTML tags from description."""
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&#x2019;", "'").replace("&#x2018;", "'")
        text = text.replace("&nbsp;", " ").replace("&#39;", "'")
        return text.strip()

    # ── Extension API ──────────────────────────────────────────────────────

    def get_popular(self, page: int = 1) -> Tuple[List[Manga], bool]:
        data = self._gql(SEARCH_QUERY, {
            "search": {"sortBy": "Popular"},
            "limit": 26,
            "page": page,
        })
        edges = (data.get("mangas") or {}).get("edges") or []
        mangas = [self._node_to_manga(e) for e in edges]
        return mangas, len(mangas) == 26

    def get_latest(self, page: int = 1) -> Tuple[List[Manga], bool]:
        data = self._gql(SEARCH_QUERY, {
            "search": {"sortBy": "Latest_Update"},
            "limit": 26,
            "page": page,
        })
        edges = (data.get("mangas") or {}).get("edges") or []
        mangas = [self._node_to_manga(e) for e in edges]
        return mangas, len(mangas) == 26

    def search(self, filters: SearchFilter, page: int = 1) -> Tuple[List[Manga], bool]:
        search_params: dict = {}
        if filters.query:
            search_params["query"] = filters.query

        sort_map = {
            "relevance": "Top",
            "popularity": "Popular",
            "latest": "Latest_Update",
            "title": "Name_ASC",
        }
        search_params["sortBy"] = sort_map.get(filters.sort_by, "Top")

        if filters.genres:
            search_params["genres"] = filters.genres

        data = self._gql(SEARCH_QUERY, {
            "search": search_params,
            "limit": 26,
            "page": page,
        })
        edges = data.get("mangas", {}).get("edges") or []
        mangas = [self._node_to_manga(e) for e in edges]
        return mangas, len(mangas) == 26

    def get_manga_details(self, manga: Manga) -> Manga:
        data = self._gql(MANGA_DETAIL_QUERY, {"id": manga.source_manga_id})
        node = data.get("manga")
        if not node:
            return manga
        updated = self._node_to_manga(node)
        # Preserve library state
        updated.id = manga.id
        updated.in_library = manga.in_library
        updated.reading_status = manga.reading_status
        updated.added_at = manga.added_at
        return updated

    def get_chapters(self, manga: Manga) -> List[Chapter]:
        """
        AllManga stores available chapters as:
        availableChaptersDetail: { "sub": ["1", "2", ...], "raw": [...] }
        We build a Chapter per chapter string.
        """
        data = self._gql(MANGA_DETAIL_QUERY, {"id": manga.source_manga_id})
        node = data.get("manga") or {}

        available = node.get("availableChaptersDetail") or {}
        # Prefer preferred translation type, fall back to other
        chapter_strings = (
            available.get(self._translation_type) or
            available.get("sub") or
            available.get("raw") or
            []
        )
        trans = (
            self._translation_type
            if available.get(self._translation_type)
            else ("sub" if available.get("sub") else "raw")
        )

        chapters = []
        for ch_str in chapter_strings:
            ch = Chapter()
            ch.manga_id = manga.id or 0
            ch.source_chapter_id = f"{manga.source_manga_id}_{trans}_{ch_str}"
            ch.scanlator = trans
            try:
                ch.chapter_number = float(ch_str)
            except ValueError:
                ch.chapter_number = -1
                ch.title = ch_str
            ch.title = ch.title or f"Chapter {ch_str}"
            # URL encodes manga_id, chapter_str, and translation type for page fetching
            ch.url = f"{manga.source_manga_id}::{ch_str}::{trans}"
            chapters.append(ch)

        return chapters

    def get_pages(self, chapter: Chapter) -> List[Page]:
        """Fetch page image URLs for a chapter."""
        parts = chapter.url.split("::")
        if len(parts) < 3:
            return []
        manga_id, chapter_str, trans = parts[0], parts[1], parts[2]

        data = self._gql(CHAPTER_PAGES_QUERY, {
            "mangaId": manga_id,
            "translationType": trans,
            "chapterString": chapter_str,
        })
        edges = (data.get("chapterPages") or {}).get("edges") or []
        pages = []
        for edge in edges:
            url_head = edge.get("pictureUrlHead") or CDN_URL
            pic_urls = edge.get("pictureUrls") or []
            for pic in pic_urls:
                url = pic.get("url") or ""
                if not url:
                    continue
                p = Page(
                    index=pic.get("num", len(pages)),
                    url=url,
                    image_url=self._resolve_page_url(url, url_head),
                )
                pages.append(p)

        # Sort by index
        pages.sort(key=lambda p: p.index)
        return pages

    # ── Settings ───────────────────────────────────────────────────────────

    def has_settings(self) -> bool:
        return True

    def get_settings(self) -> dict:
        return {
            "translation_type": {
                "type": "select",
                "label": "Preferred Translation",
                "options": ["sub", "raw"],
                "current": self._translation_type,
            }
        }

    def save_settings(self, settings: dict):
        if "translation_type" in settings:
            self._translation_type = settings["translation_type"]
