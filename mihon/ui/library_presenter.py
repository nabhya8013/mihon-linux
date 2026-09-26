"""
Library presenter: the library's data and filtering logic, without GTK.

``LibraryView`` used to hold ``_all_manga``, ``_filtered_manga``,
``_search_query``, the per-category preferences and the category list as
widget instance state, which meant none of it could be exercised without
instantiating GTK widgets. This module owns that state instead. The view
subscribes and re-renders when the presenter says something changed.

The presenter never touches a widget, and it never calls ``GLib.idle_add``.
Background loading stays the view's job: it calls :meth:`load_from` on a
worker thread and hands the result to :meth:`set_loaded` on the main thread.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence, Set

from ..core.models import Manga
from .library_state import LibraryPreferences, apply_library_preferences

logger = logging.getLogger("library_presenter")

# Setting key holding the preferences used when no category is selected, and
# the template for a per-category override.
GLOBAL_PREFS_KEY = "library_prefs_global"
CATEGORY_PREFS_KEY = "library_prefs_category_{}"


def prefs_key_for_category(category_id: Optional[int]) -> str:
    """Setting key holding the preferences for one category."""
    if category_id is None:
        return GLOBAL_PREFS_KEY
    return CATEGORY_PREFS_KEY.format(category_id)


class LibraryPresenter:
    """
    Owns the library's data and the filter/sort state applied to it.

    Observers registered with :meth:`subscribe` are called with the presenter
    whenever the visible list may have changed. Every mutating method funnels
    through :meth:`_recompute`, so a view can re-render from one callback
    rather than from a dozen individual signals.
    """

    def __init__(self, db, prefs_loader: Optional[Callable] = None):
        self._db = db
        self._observers: List[Callable] = []

        self._all_manga: List[Manga] = []
        self._visible_manga: List[Manga] = []
        self._downloaded_ids: Set[int] = set()
        self._categories: List = []

        self._search_query = ""
        self._category_id: Optional[int] = None
        self._prefs = (prefs_loader or self.load_preferences)(None)

    # ── Observation ───────────────────────────────────────────────────────

    def subscribe(self, callback: Callable):
        """Register a callback invoked whenever the visible list changes."""
        if callback not in self._observers:
            self._observers.append(callback)

    def unsubscribe(self, callback: Callable):
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify(self):
        for callback in list(self._observers):
            try:
                callback(self)
            except Exception as exc:
                logger.warning("library observer failed: %s", exc)

    # ── Read-only state ───────────────────────────────────────────────────

    @property
    def visible_manga(self) -> List[Manga]:
        """The manga to draw, after search, filters and sorting."""
        return self._visible_manga

    @property
    def all_manga(self) -> List[Manga]:
        """Everything loaded for the current category, unfiltered."""
        return self._all_manga

    @property
    def categories(self) -> List:
        return self._categories

    @property
    def category_id(self) -> Optional[int]:
        return self._category_id

    @property
    def prefs(self) -> LibraryPreferences:
        return self._prefs

    @property
    def search_query(self) -> str:
        return self._search_query

    @property
    def downloaded_ids(self) -> Set[int]:
        return set(self._downloaded_ids)

    @property
    def is_empty(self) -> bool:
        return not self._visible_manga

    @property
    def is_filtered_empty(self) -> bool:
        """True when the library has manga but nothing survives the filters."""
        return bool(self._all_manga) and not self._visible_manga

    def visible_ids(self) -> List[int]:
        """Row ids of the visible manga, for a batch action."""
        return [m.id for m in self._visible_manga if m.id is not None]

    def category_name(self, category_id: Optional[int]) -> str:
        if category_id is None:
            return "All"
        for category in self._categories:
            if category.id == category_id:
                return category.name
        return ""

    # ── Loading ───────────────────────────────────────────────────────────

    def load_from_db(self):
        """
        Read the current category from the database.

        Safe to call from a worker thread — it only reads. Pass the result to
        :meth:`set_loaded` on the main thread.
        """
        manga = self._db.get_library(self._category_id)
        categories = self._db.get_categories()
        manga_ids = [m.id for m in manga if m.id is not None]
        downloaded = self._db.get_downloaded_manga_ids(manga_ids)
        return manga, categories, downloaded

    def set_loaded(self, manga: Sequence[Manga], categories: Sequence, downloaded_ids):
        self._all_manga = list(manga or [])
        self._categories = list(categories or [])
        self._downloaded_ids = set(downloaded_ids or ())
        self._recompute()

    # ── Mutation ──────────────────────────────────────────────────────────

    def set_search_query(self, query: str):
        query = (query or "").strip().lower()
        if query == self._search_query:
            return
        self._search_query = query
        self._recompute()

    def set_category(self, category_id: Optional[int]) -> bool:
        """
        Switch category, persisting the outgoing category's preferences.

        Returns True when the category actually changed, which tells the view
        it needs to reload from the database.
        """
        if category_id == self._category_id:
            return False
        self.persist_preferences()
        self._category_id = category_id
        self._prefs = self.load_preferences(category_id)
        # The old category's rows no longer apply; clear them so a slow reload
        # cannot leave the previous category's manga on screen.
        self._all_manga = []
        self._recompute()
        return True

    def update_prefs(self, **changes) -> bool:
        """
        Apply preference changes by field name and persist them.

        Returns True when something actually changed, so a view can skip a
        redraw when a control re-emits its current value.
        """
        changed = False
        for field, value in changes.items():
            if not hasattr(self._prefs, field):
                logger.warning("unknown library preference: %s", field)
                continue
            if getattr(self._prefs, field) != value:
                setattr(self._prefs, field, value)
                changed = True
        if not changed:
            return False
        self.persist_preferences()
        self._recompute()
        return True

    def reset_prefs(self):
        """Back to defaults for the current category, search included."""
        self._prefs = LibraryPreferences()
        self._search_query = ""
        self.persist_preferences()
        self._recompute()

    def update_manga(self, manga: Manga) -> bool:
        """Replace one loaded manga in place, matched on row id."""
        if manga is None or manga.id is None:
            return False
        for index, existing in enumerate(self._all_manga):
            if existing.id == manga.id:
                self._all_manga[index] = manga
                self._recompute()
                return True
        return False

    # ── Preferences ───────────────────────────────────────────────────────

    def load_preferences(self, category_id: Optional[int]) -> LibraryPreferences:
        """
        Preferences for a category, falling back to the global ones.

        A category the user has never configured inherits whatever they set
        with no category selected, rather than snapping back to defaults.
        """
        raw = self._db.get_setting(prefs_key_for_category(category_id), "")
        if raw:
            return LibraryPreferences.from_json(raw)
        if category_id is not None:
            fallback = self._db.get_setting(GLOBAL_PREFS_KEY, "")
            if fallback:
                return LibraryPreferences.from_json(fallback)
        return LibraryPreferences()

    def persist_preferences(self):
        """Write the current preferences back for the current category."""
        self._db.set_setting(
            prefs_key_for_category(self._category_id), self._prefs.to_json()
        )

    # ── Internals ─────────────────────────────────────────────────────────

    def _recompute(self):
        self._visible_manga = apply_library_preferences(
            manga_list=self._all_manga,
            prefs=self._prefs,
            search_query=self._search_query,
            downloaded_manga_ids=self._downloaded_ids,
        )
        self._notify()


__all__ = [
    "CATEGORY_PREFS_KEY",
    "GLOBAL_PREFS_KEY",
    "LibraryPresenter",
    "prefs_key_for_category",
]
