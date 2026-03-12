"""
Async image loader with caching for GTK4.
Fetches images in background threads and loads them as GdkPixbuf.
"""
import threading
import os
import hashlib
import requests
from pathlib import Path
from typing import Callable, Optional
from gi.repository import GLib, GdkPixbuf, Gio
from .database import COVERS_DIR


# In-memory cache: url -> GdkPixbuf
_pixbuf_cache: dict = {}
_cache_lock = threading.Lock()

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
})

# Map URL domains to their correct Referer headers
_REFERER_MAP = {
    "mangadex.org": "https://mangadex.org",
    "uploads.mangadex.org": "https://mangadex.org",
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


def _cache_path(url: str) -> Path:
    h = hashlib.md5(url.encode()).hexdigest()
    return COVERS_DIR / h


def load_image_async(
    url: str,
    callback: Callable[[Optional[GdkPixbuf.Pixbuf]], None],
    width: int = -1,
    height: int = -1,
    preserve_aspect: bool = True,
):
    """
    Load an image from URL asynchronously.
    Calls callback(pixbuf) on the GTK main thread when done.
    callback receives None on failure.
    """
    if not url:
        GLib.idle_add(callback, None)
        return

    with _cache_lock:
        key = f"{url}_{width}_{height}"
        if key in _pixbuf_cache:
            pixbuf = _pixbuf_cache[key]
            GLib.idle_add(callback, pixbuf)
            return

    def fetch():
        try:
            cache_file = _cache_path(url)
            if cache_file.exists():
                data = cache_file.read_bytes()
            else:
                headers = {}
                referer = _get_referer(url)
                if referer:
                    headers["Referer"] = referer
                resp = SESSION.get(url, timeout=15, headers=headers)
                resp.raise_for_status()
                data = resp.content
                cache_file.write_bytes(data)

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

            with _cache_lock:
                _pixbuf_cache[key] = pixbuf

            GLib.idle_add(callback, pixbuf)
        except Exception as e:
            print(f"[image_loader] Failed to load {url}: {e}")
            GLib.idle_add(callback, None)

    t = threading.Thread(target=fetch, daemon=True)
    t.start()


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


def clear_cache():
    with _cache_lock:
        _pixbuf_cache.clear()
