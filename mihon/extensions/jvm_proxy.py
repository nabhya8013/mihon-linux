"""
JVM Proxy Extension — wraps a JVM-loaded Tachiyomi extension behind
the native Python Extension ABC so the GTK UI can use it seamlessly.

Each loaded JVM source gets one JvmProxyExtension instance that translates
calls into JSON-RPC requests to the bridge.
"""
import logging
from typing import List, Tuple, Optional
from .base import Extension
from .jvm_bridge import get_bridge, BridgeError
from ..core.models import Manga, Chapter, Page, SearchFilter, ExtensionInfo

logger = logging.getLogger("jvm_proxy")


class JvmProxyExtension(Extension):
    """
    Proxy that implements the Extension ABC by forwarding every call
    to a JVM-loaded Tachiyomi source via the JSON-RPC bridge.
    """

    def __init__(self, extension_id: int, name: str, lang: str,
                 base_url: str = "", supports_latest: bool = False):
        self._extension_id = extension_id
        self._name = name
        self._lang = lang
        self._base_url = base_url
        self._supports_latest = supports_latest

    @property
    def info(self) -> ExtensionInfo:
        return ExtensionInfo(
            id=f"jvm_{self._extension_id}",
            name=self._name,
            version="1.0.0",
            language=self._lang,
            description=f"{self._name} (JVM Extension)",
            installed=True,
            has_settings=False,
            nsfw=False,
        )

    # ── Bridge call helper ────────────────────────────────────────────────

    def _call(self, method: str, params: dict = None, timeout: float = 30.0):
        """Call the JVM bridge, injecting our extensionId automatically."""
        p = {"extensionId": self._extension_id}
        if params:
            p.update(params)
        return get_bridge().call(method, p, timeout=timeout)

    # ── Browsing ──────────────────────────────────────────────────────────

    def get_popular(self, page: int = 1) -> Tuple[List[Manga], bool]:
        try:
            result = self._call("extension.popular", {"page": page})
            mangas = [self._to_manga(m) for m in result.get("mangas", [])]
            return mangas, result.get("hasNextPage", False)
        except BridgeError as e:
            logger.error(f"[{self._name}] get_popular failed: {e}")
            return [], False

    def get_latest(self, page: int = 1) -> Tuple[List[Manga], bool]:
        if not self._supports_latest:
            return [], False
        try:
            result = self._call("extension.latest", {"page": page})
            mangas = [self._to_manga(m) for m in result.get("mangas", [])]
            return mangas, result.get("hasNextPage", False)
        except BridgeError as e:
            logger.error(f"[{self._name}] get_latest failed: {e}")
            return [], False

    def search(self, filters: SearchFilter, page: int = 1) -> Tuple[List[Manga], bool]:
        try:
            result = self._call("extension.search", {
                "page": page,
                "query": filters.query,
            })
            mangas = [self._to_manga(m) for m in result.get("mangas", [])]
            return mangas, result.get("hasNextPage", False)
        except BridgeError as e:
            logger.error(f"[{self._name}] search failed: {e}")
            return [], False

    # ── Details ───────────────────────────────────────────────────────────

    def get_manga_details(self, manga: Manga) -> Manga:
        try:
            result = self._call("extension.details", {
                "mangaUrl": manga.url or manga.source_manga_id,
                "manga": self._to_bridge_manga(manga),
            })
            updated = self._to_manga(result)
            # Preserve library state
            updated.id = manga.id
            updated.in_library = manga.in_library
            updated.reading_status = manga.reading_status
            updated.added_at = manga.added_at
            return updated
        except BridgeError as e:
            logger.error(f"[{self._name}] get_manga_details failed: {e}")
            print(f"[jvm_proxy] get_manga_details failed for {self._name}: {e}")
            return manga

    def get_chapters(self, manga: Manga) -> List[Chapter]:
        try:
            result = self._call("extension.chapters", {
                "mangaUrl": manga.url or manga.source_manga_id,
                "manga": self._to_bridge_manga(manga),
            }, timeout=60.0)
            chapters = []
            for ch_data in result:
                ch = Chapter()
                ch.manga_id = manga.id or 0
                ch.source_chapter_id = ch_data.get("url", "")
                ch.title = ch_data.get("name", "")
                ch.chapter_number = ch_data.get("chapterNumber", -1.0)
                ch.scanlator = ch_data.get("scanlator", "")
                ch.uploaded_at = ch_data.get("dateUpload", 0) / 1000.0 if ch_data.get("dateUpload") else None
                ch.url = ch_data.get("url", "")
                chapters.append(ch)
            return chapters
        except BridgeError as e:
            logger.error(f"[{self._name}] get_chapters failed: {e}")
            print(f"[jvm_proxy] get_chapters failed for {self._name}: {e}")
            return []

    def get_pages(self, chapter: Chapter) -> List[Page]:
        try:
            result = self._call("extension.pages", {
                "chapterUrl": chapter.url or chapter.source_chapter_id,
            }, timeout=60.0)
            pages = []
            for pg_data in result:
                p = Page(
                    index=pg_data.get("index", len(pages)),
                    url=pg_data.get("url", ""),
                    image_url=pg_data.get("imageUrl", "") or pg_data.get("url", ""),
                )
                pages.append(p)
            return pages
        except BridgeError as e:
            logger.error(f"[{self._name}] get_pages failed: {e}")
            print(f"[jvm_proxy] get_pages failed for {self._name}: {e}")
            return []

    # ── Converter ─────────────────────────────────────────────────────────

    def _to_bridge_manga(self, manga: Manga) -> dict:
        status_map = {
            "ongoing": 1,
            "completed": 2,
            "licensed": 3,
            "cancelled": 5,
            "hiatus": 6,
        }
        return {
            "url": manga.url or manga.source_manga_id,
            "title": manga.title,
            "artist": manga.artist,
            "author": manga.author,
            "description": manga.description,
            "genre": ", ".join(manga.genres) if manga.genres else "",
            "status": status_map.get(manga.status, 0),
            "thumbnailUrl": manga.cover_url,
            "initialized": True,
        }

    def _to_manga(self, data: dict) -> Manga:
        """Convert a bridge BridgeManga dict to our Manga model."""
        if not data:
            return Manga()

        status_map = {
            0: "",        # UNKNOWN
            1: "ongoing",
            2: "completed",
            3: "licensed",
            4: "completed",  # PUBLISHING_FINISHED
            5: "cancelled",
            6: "hiatus",
        }

        m = Manga()
        m.source_id = self.info.id
        m.source_manga_id = data.get("url", "")
        m.title = data.get("title", "")
        m.author = data.get("author", "")
        m.artist = data.get("artist", "")
        m.description = data.get("description", "")
        m.cover_url = data.get("thumbnailUrl", "")
        m.url = data.get("url", "")

        raw_status = data.get("status", 0)
        m.status = status_map.get(raw_status, "")

        genre_str = data.get("genre", "")
        if genre_str:
            m.genres = [g.strip() for g in genre_str.split(",") if g.strip()]

        return m
