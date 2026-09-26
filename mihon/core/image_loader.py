"""
Async image loader with caching for GTK4.
Fetches images in background threads and loads them as GdkPixbuf.
"""
import threading
from collections import OrderedDict
from typing import Callable, Optional
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GLib, GdkPixbuf, Gio
from . import disk_cache
from .http_client import create_http_session
import logging

logger = logging.getLogger("image_loader")


# In-memory cache: "url_width_height" -> GdkPixbuf, most recently used last.
# Decoded manga pages are large — a 50-page chapter at full resolution runs to
# hundreds of megabytes — so the cache is bounded and evicts least-recently
# used entries. The reader raises the limit to cover its prefetch window.
DEFAULT_CACHE_LIMIT = 60

_pixbuf_cache: "OrderedDict[str, GdkPixbuf.Pixbuf]" = OrderedDict()
_cache_limit = DEFAULT_CACHE_LIMIT
_cache_lock = threading.Lock()
# URLs with a fetch already in flight, so a prefetch does not duplicate work.
_inflight: set = set()


def _cache_key(url: str, width: int, height: int) -> str:
    return f"{url}_{width}_{height}"


def set_cache_limit(limit: int):
    """Cap how many decoded images stay in memory. Evicts immediately."""
    global _cache_limit
    with _cache_lock:
        _cache_limit = max(1, int(limit))
        _trim_locked()


def _trim_locked():
    """Drop least-recently-used entries. Caller must hold _cache_lock."""
    while len(_pixbuf_cache) > _cache_limit:
        _pixbuf_cache.popitem(last=False)


def _cache_get(key: str):
    with _cache_lock:
        pixbuf = _pixbuf_cache.get(key)
        if pixbuf is not None:
            _pixbuf_cache.move_to_end(key)
        return pixbuf


def _cache_put(key: str, pixbuf):
    with _cache_lock:
        _pixbuf_cache[key] = pixbuf
        _pixbuf_cache.move_to_end(key)
        _trim_locked()


def evict(url: str, width: int = -1, height: int = -1):
    """Drop one decoded image from memory. The disk cache is untouched."""
    with _cache_lock:
        _pixbuf_cache.pop(_cache_key(url, width, height), None)


def is_cached(url: str, width: int = -1, height: int = -1) -> bool:
    with _cache_lock:
        return _cache_key(url, width, height) in _pixbuf_cache


def cache_size() -> int:
    with _cache_lock:
        return len(_pixbuf_cache)


SESSION = create_http_session()

# Map URL domains to their correct Referer headers
_REFERER_MAP = {
    "mangadex.org": "https://mangadex.org",
    "uploads.mangadex.org": "https://mangadex.org",
    "mangadex.network": "https://mangadex.org",
    "allmanga.to": "https://allmanga.to",
    "allanime.day": "https://allmanga.to",
    "aln.youtube-anime.com": "https://allmanga.to",
}


def _get_referer(url: str) -> str:
    """Return the appropriate Referer header for a given URL."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        for domain, referer in _REFERER_MAP.items():
            if host == domain or host.endswith("." + domain):
                return referer
    except Exception:
        pass
    return ""


def load_image_async(
    url: str,
    callback: Callable[[Optional[GdkPixbuf.Pixbuf]], None],
    width: int = -1,
    height: int = -1,
    preserve_aspect: bool = True,
    kind: str = disk_cache.KIND_PAGE,
):
    """
    Load an image from URL asynchronously.
    Calls callback(pixbuf) on the GTK main thread when done.
    callback receives None on failure.

    ``kind`` picks the on-disk cache: covers are kept, pages are pruned once
    the page cache outgrows its size limit.
    """
    if not url:
        GLib.idle_add(callback, None)
        return

    key = _cache_key(url, width, height)
    cached = _cache_get(key)
    if cached is not None:
        GLib.idle_add(callback, cached)
        return

    with _cache_lock:
        _inflight.add(key)

    def fetch():
        try:
            data = disk_cache.read(url, kind)
            if data is None:
                headers = {}
                referer = _get_referer(url)
                if referer:
                    headers["Referer"] = referer
                resp = SESSION.get(url, timeout=15, headers=headers)
                resp.raise_for_status()
                data = resp.content
                disk_cache.write(url, data, kind)

            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()

            if pixbuf and (width > 0 or height > 0):
                orig_w = pixbuf.get_width()
                orig_h = pixbuf.get_height()
                if preserve_aspect:
                    if width > 0 and height > 0:
                        scale = min(width / orig_w, height / orig_h)
                    elif width > 0:
                        scale = width / orig_w
                    else:
                        scale = height / orig_h
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                else:
                    new_w = width if width > 0 else orig_w
                    new_h = height if height > 0 else orig_h
                pixbuf = pixbuf.scale_simple(new_w, new_h, GdkPixbuf.InterpType.BILINEAR)

            _cache_put(key, pixbuf)
            GLib.idle_add(callback, pixbuf)
        except Exception as e:
            logger.warning("failed to load %s: %s", url, e)
            GLib.idle_add(callback, None)
        finally:
            with _cache_lock:
                _inflight.discard(key)

    t = threading.Thread(target=fetch, daemon=True)
    t.start()


def cached_path(url: str, kind: str = disk_cache.KIND_PAGE) -> Optional[str]:
    """The on-disk path for a URL, if it has been cached. Else None."""
    path = disk_cache.cache_path(url, kind)
    return str(path) if path.exists() else None


def load_local_image(path: str, width: int = -1, height: int = -1) -> Optional[GdkPixbuf.Pixbuf]:
    """Synchronously load a local image file."""
    try:
        if width > 0 or height > 0:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                path, width, height, True
            )
        else:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        return pixbuf
    except Exception:
        return None


def is_loading(url: str, width: int = -1, height: int = -1) -> bool:
    with _cache_lock:
        return _cache_key(url, width, height) in _inflight


def prefetch(url: str, width: int = -1, height: int = -1, kind: str = disk_cache.KIND_PAGE):
    """
    Warm the cache for a URL without rendering it.

    A no-op when the image is already cached or a fetch for it is in flight,
    so repeated prefetch passes over an overlapping window cost nothing.
    """
    if not url or is_cached(url, width, height) or is_loading(url, width, height):
        return
    load_image_async(url, lambda _pb: None, width=width, height=height, kind=kind)


def clear_cache():
    with _cache_lock:
        _pixbuf_cache.clear()
