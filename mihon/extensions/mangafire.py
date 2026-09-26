"""
MangaFire (mangafire.to) extension for Mihon Linux.
Uses MangaFire's REST API. Anti-bot challenges (Cloudflare 403/503) are
handled transparently by the shared HTTP session's WebKit challenge solver.
"""

from typing import List, Tuple
from .base import Extension
from ..core.http_client import create_http_session
from ..core.models import Manga, Chapter, Page, SearchFilter, ExtensionInfo


API_URL = "https://mangafire.to/api"
BASE_URL = "https://mangafire.to"


class MangaFireExtension(Extension):
    def __init__(self):
        self._session = create_http_session()

    @property
    def info(self) -> ExtensionInfo:
        return ExtensionInfo(
            id="mangafire",
            name="MangaFire",
            version="1.0.0",
            language="en",
            description="MangaFire.to — manga and manhwa library",
            installed=True,
            has_settings=False,
            nsfw=True,  # MangaFire has adult content
        )

    def _get(self, path: str, params: dict = None) -> dict:
        """Make a GET request to the MangaFire API."""
        url = f"{API_URL}{path}"
        try:
            resp = self._session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[mangafire] GET {path} error: {e}")
            raise

    def _post(self, path: str, data: dict = None) -> dict:
        """Make a POST request to the MangaFire API."""
        url = f"{API_URL}{path}"
        try:
            resp = self._session.post(url, json=data, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[mangafire] POST {path} error: {e}")
            raise

    def _to_manga(self, data: dict) -> Manga:
        """Convert MangaFire manga DTO to Mihon Manga model."""
        if not data:
            return Manga()
        
        m = Manga()
        m.source_id = self.id
        m.source_manga_id = str(data.get("id", ""))
        m.title = str(data.get("title", ""))
        
        # Alt titles
        alt_titles = []
        if data.get("alternativeTitles"):
            alt_titles.extend(data["alternativeTitles"])
        if data.get("nativeTitle"):
            alt_titles.append(data["nativeTitle"])
        m.alt_titles = list(filter(None, alt_titles))
        
        m.description = str(data.get("description", ""))
        
        # Genres/tags
        if data.get("genres"):
            m.genres = [str(g) for g in data["genres"]]
        
        # Authors
        if data.get("authors"):
            m.author = ", ".join(data["authors"])
            m.artist = m.author
        
        # Status
        status_map = {
            "Ongoing": "ongoing",
            "Completed": "completed",
            "Hiatus": "hiatus",
            "Cancelled": "cancelled",
            "Not yet released": "upcoming",
        }
        raw_status = str(data.get("status", ""))
        m.status = status_map.get(raw_status, raw_status.lower())
        
        # Score/rating
        try:
            m.score = float(data.get("rating", 0)) if data.get("rating") else 0.0
        except (ValueError, TypeError):
            m.score = 0.0
        
        # Year from release date
        if data.get("releaseDate"):
            try:
                # Format: "YYYY-MM-DD"
                year_str = data["releaseDate"].split("-")[0]
                m.year = int(year_str)
            except (ValueError, TypeError, IndexError):
                m.year = None
        
        # Cover image
        if data.get("cover"):
            cover = data["cover"]
            if isinstance(cover, str) and cover:
                m.cover_url = cover if cover.startswith("http") else f"{BASE_URL}{cover}"
        
        m.url = f"{BASE_URL}/manga/{m.source_manga_id}"
        m.content_rating = "safe" if data.get("isAdult") == False else "nsfw"
        
        return m

    def _to_chapter(self, manga_id: str, data: dict) -> Chapter:
        """Convert MangaFire chapter DTO to Mihon Chapter model."""
        if not data:
            return Chapter()
        
        ch = Chapter()
        ch.manga_id = int(manga_id) if manga_id.isdigit() else 0
        ch.source_chapter_id = str(data.get("id", ""))
        ch.title = str(data.get("chapter", "")) or f"Chapter {data.get('chapter', '?')}"
        
        try:
            ch.chapter_number = float(data.get("chapterNumber", 0)) if data.get("chapterNumber") else -1
        except (ValueError, TypeError):
            ch.chapter_number = -1
        
        # Scanlator/language
        ch.scanlator = str(data.get("language", "en")) if data.get("language") else "en"
        
        # Date
        if data.get("dateUpdated"):
            try:
                # Assume ISO format
                ch.date_updated = data["dateUpdated"]
            except:
                pass
        
        ch.url = str(data.get("id", ""))  # Will be expanded in get_pages
        return ch

    def _to_page(self, data: dict, base_url: str = "") -> Page:
        """Convert MangaFire page DTO to Mihon Page model."""
        if not data:
            return Page()
        
        p = Page()
        try:
            p.index = int(data.get("page", 0)) if data.get("page") is not None else 0
        except (ValueError, TypeError):
            p.index = 0
        
        img_url = str(data.get("url", "")) if data.get("url") else ""
        if img_url:
            if not img_url.startswith("http"):
                img_url = base_url + img_url if base_url else img_url
            p.url = img_url
            p.image_url = img_url
        
        return p

    # ── Extension API ──────────────────────────────────────────────────────

    def get_popular(self, page: int = 1) -> Tuple[List[Manga], bool]:
        """Get popular manga."""
        try:
            data = self._get("/titles", {
                "sort": "popular",
                "page": page,
                "limit": 20
            })
            
            manga_list = data.get("data", []) if isinstance(data, dict) else []
            mangas = [self._to_manga(m) for m in manga_list]
            
            has_more = len(mangas) >= 20
            return mangas, has_more
        except Exception as e:
            print(f"[mangafire] get_popular error: {e}")
            return [], False

    def get_latest(self, page: int = 1) -> Tuple[List[Manga], bool]:
        """Get latest updated manga."""
        try:
            data = self._get("/titles", {
                "sort": "latest",
                "page": page,
                "limit": 20
            })
            
            manga_list = data.get("data", []) if isinstance(data, dict) else []
            mangas = [self._to_manga(m) for m in manga_list]
            
            has_more = len(mangas) >= 20
            return mangas, has_more
        except Exception as e:
            print(f"[mangafire] get_latest error: {e}")
            return [], False

    def search(self, filters: SearchFilter, page: int = 1) -> Tuple[List[Manga], bool]:
        """Search for manga."""
        try:
            params = {
                "page": page,
                "limit": 20
            }
            
            if filters.query:
                params["keyword"] = filters.query
            
            # Map sort options
            sort_map = {
                "relevance": "relevant",
                "popularity": "popular",
                "latest": "latest",
                "title": "title"
            }
            if filters.sort_by in sort_map:
                params["sort"] = sort_map[filters.sort_by]
            
            data = self._get("/titles", params)
            manga_list = data.get("data", []) if isinstance(data, dict) else []
            mangas = [self._to_manga(m) for m in manga_list]
            
            has_more = len(mangas) >= 20
            return mangas, has_more
        except Exception as e:
            print(f"[mangafire] search error: {e}")
            return [], False

    def get_manga_details(self, manga: Manga) -> Manga:
        """Get detailed manga information."""
        try:
            data = self._get(f"/manga/{manga.source_manga_id}")
            manga_data = data.get("data", {}) if isinstance(data, dict) else {}
            updated = self._to_manga(manga_data)
            
            # Preserve library state
            updated.id = manga.id
            updated.in_library = manga.in_library
            updated.reading_status = manga.reading_status
            updated.added_at = manga.added_at
            return updated
        except Exception as e:
            print(f"[mangafire] get_manga_details error: {e}")
            return manga

    def get_chapters(self, manga: Manga) -> List[Chapter]:
        """Get manga chapters."""
        try:
            data = self._get(f"/manga/{manga.source_manga_id}/chapters")
            chapters_data = data.get("data", []) if isinstance(data, dict) else []
            chapters = [self._to_chapter(manga.source_manga_id, c) for c in chapters_data]
            return chapters
        except Exception as e:
            print(f"[mangafire] get_chapters error: {e}")
            return []

    def get_pages(self, chapter: Chapter) -> List[Page]:
        """Get chapter pages."""
        try:
            # Try to get chapter details first for better data
            chapter_data = self._get(f"/chapter/{chapter.source_chapter_id}")
            chapter_info = chapter_data.get("data", {}) if isinstance(chapter_data, dict) else {}
            
            # Get actual pages
            data = self._get(f"/chapter/{chapter.source_chapter_id}/pages")
            pages_data = data.get("data", []) if isinstance(data, dict) else []
            
            # Extract base URL for relative image paths
            base_url = ""
            if chapter_info.get("cdn"):
                base_url = chapter_info["cdn"]
            elif chapter_info.get("server"):
                base_url = chapter_info["server"]
            
            pages = [self._to_page(p, base_url) for p in pages_data]
            pages.sort(key=lambda p: p.index)
            return pages
        except Exception as e:
            print(f"[mangafire] get_pages error: {e}")
            return []


# Auto-register the extension
def register():
    return MangaFireExtension()