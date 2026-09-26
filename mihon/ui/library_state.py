"""
Library filter/sort/display state engine.
Keeps view logic separate from GTK widgets.
"""
from dataclasses import dataclass, field
from typing import List, Iterable, Set
import json

from ..core.models import Manga


SORT_OPTIONS = {
    "title": "Title",
    "unread_count": "Unread Count",
    "recently_added": "Recently Added",
    "last_read": "Last Read",
}

DISPLAY_MODES = {
    "grid": "Grid",
    "list": "List",
}


@dataclass
class LibraryPreferences:
    sort_by: str = "title"
    sort_desc: bool = False
    display_mode: str = "grid"
    status_filters: List[str] = field(default_factory=list)
    unread_only: bool = False
    downloaded_only: bool = False

    def to_json(self) -> str:
        return json.dumps({
            "sort_by": self.sort_by,
            "sort_desc": self.sort_desc,
            "display_mode": self.display_mode,
            "status_filters": self.status_filters,
            "unread_only": self.unread_only,
            "downloaded_only": self.downloaded_only,
        })

    @classmethod
    def from_json(cls, raw: str) -> "LibraryPreferences":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except Exception:
            return cls()
        prefs = cls()
        sort_by = str(data.get("sort_by", prefs.sort_by))
        prefs.sort_by = sort_by if sort_by in SORT_OPTIONS else prefs.sort_by
        prefs.sort_desc = bool(data.get("sort_desc", prefs.sort_desc))
        display_mode = str(data.get("display_mode", prefs.display_mode))
        prefs.display_mode = display_mode if display_mode in DISPLAY_MODES else prefs.display_mode
        statuses = data.get("status_filters", [])
        if isinstance(statuses, list):
            prefs.status_filters = [str(s) for s in statuses]
        prefs.unread_only = bool(data.get("unread_only", prefs.unread_only))
        prefs.downloaded_only = bool(data.get("downloaded_only", prefs.downloaded_only))
        return prefs


def apply_library_preferences(
    manga_list: Iterable[Manga],
    prefs: LibraryPreferences,
    search_query: str,
    downloaded_manga_ids: Set[int],
) -> List[Manga]:
    """Apply search, filter, and sort rules in a deterministic order."""
    query = (search_query or "").strip().lower()
    result = list(manga_list)

    if query:
        result = [
            m for m in result
            if query in (m.title or "").lower() or query in (m.author or "").lower()
        ]

    if prefs.status_filters:
        allowed = set(prefs.status_filters)
        result = [m for m in result if m.reading_status.value in allowed]

    if prefs.unread_only:
        result = [m for m in result if (m.unread_count or 0) > 0]

    if prefs.downloaded_only:
        result = [m for m in result if m.id in downloaded_manga_ids]

    if prefs.sort_by == "unread_count":
        key_fn = lambda m: ((m.unread_count or 0), (m.title or "").lower())
    elif prefs.sort_by == "recently_added":
        key_fn = lambda m: (m.added_at or 0, (m.title or "").lower())
    elif prefs.sort_by == "last_read":
        key_fn = lambda m: (m.last_read_at or 0, (m.title or "").lower())
    else:
        key_fn = lambda m: (m.title or "").lower()

    reverse = prefs.sort_desc
    result.sort(key=key_fn, reverse=reverse)
    return result
