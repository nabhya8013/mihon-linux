"""
Source id mapping between this app and Android Mihon.

Android identifies a source by a 64-bit number derived from the source's
name, language and version. This app identifies a source by a string: a
built-in source's own name (``"mangadex"``), or ``"mihon:<number>"`` for
anything that arrived from a backup or a JVM extension.

Both directions live here so the importer and the exporter cannot drift
apart: whatever :func:`to_android_id` writes, :func:`to_local_id` must read
back to the same local string.
"""
from __future__ import annotations

import hashlib

# Language codes for the built-in Python sources. Android derives a source's
# id from its language, so these must match what the equivalent extension
# declares or a backup will not resolve on the phone.
BUILTIN_SOURCE_LANG = {
    "mangadex": "all",
    "allmanga": "en",
    "mangafire": "en",
}


def tachiyomi_source_id(name: str, lang: str, version_id: int = 1) -> int:
    """
    Reproduce Tachiyomi/Mihon's ``HttpSource.id``.

    The Kotlin implementation hashes ``"${name.lowercase()}/$lang/$versionId"``
    with MD5, takes the first 8 bytes as a big-endian long, and masks off the
    sign bit.
    """
    key = f"{name.lower()}/{lang}/{version_id}"
    digest = hashlib.md5(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) & 0x7FFFFFFFFFFFFFFF


def _builtin_ids() -> dict:
    """Numeric id -> built-in source name, computed once per process."""
    global _BUILTIN_IDS
    if _BUILTIN_IDS is None:
        _BUILTIN_IDS = {
            tachiyomi_source_id(name, lang): name
            for name, lang in BUILTIN_SOURCE_LANG.items()
        }
    return _BUILTIN_IDS


_BUILTIN_IDS = None


def to_android_id(source_id: str) -> int:
    """
    Map a local ``Manga.source_id`` onto an Android numeric source id.

    ``"mihon:<n>"`` round-trips the number an import already carried.
    Anything else is a source name, hashed the way Android would hash it.
    """
    if not source_id:
        return 0
    if source_id.startswith("mihon:"):
        try:
            return int(source_id.split(":", 1)[1])
        except ValueError:
            return 0
    lang = BUILTIN_SOURCE_LANG.get(source_id.lower(), "en")
    return tachiyomi_source_id(source_id, lang)


def to_local_id(android_id: int) -> str:
    """
    Map an Android numeric source id back onto a local ``Manga.source_id``.

    A number belonging to a built-in source resolves to that source's name, so
    re-importing a backup this app exported updates the existing library rows
    instead of creating duplicates. Everything else keeps the ``"mihon:<n>"``
    form, which stays stable across further round trips.
    """
    builtin = _builtin_ids().get(int(android_id))
    if builtin is not None:
        return builtin
    return f"mihon:{android_id}"


__all__ = [
    "BUILTIN_SOURCE_LANG",
    "tachiyomi_source_id",
    "to_android_id",
    "to_local_id",
]
