"""
Library view - shows manga in the user's library with advanced controls.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib
import threading
from ..core.database import get_db
from ..core.models import Manga, ReadingStatus
from .widgets import MangaGridView, EmptyState, LoadingSpinner
from .library_state import (
    LibraryPreferences,
    SORT_OPTIONS,
    DISPLAY_MODES,
    apply_library_preferences,
)


class LibraryView(Gtk.Box):
    """
    Main library page showing manga in user's collection.
    Includes search, sorting, display modes, advanced filters, batch actions,
    and per-category preference persistence.
    """

    def __init__(self, on_manga_selected=None, on_show_downloads=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_manga_selected = on_manga_selected
        self._on_show_downloads = on_show_downloads
        self._db = get_db()
        self._all_manga = []
        self._filtered_manga = []
        self._downloaded_manga_ids = set()
        self._search_query = ""
        self._current_category = None  # None = All
        self._syncing_controls = False
        self._prefs = self._load_preferences_for_category(None)

        self._build_ui()
        self._sync_controls_from_prefs()
        self.reload()

    def _build_ui(self):
        # Header controls
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.set_margin_start(16)
        header_box.set_margin_end(16)
        header_box.set_margin_top(8)
        header_box.set_margin_bottom(8)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search library...")
        self._search.set_hexpand(True)
        self._search.connect("search-changed", self._on_search_changed)
        header_box.append(self._search)

        filter_btn = Gtk.MenuButton()
        filter_btn.set_icon_name("funnel-symbolic")
        filter_btn.set_tooltip_text("Advanced filters")
        filter_btn.set_popover(self._build_filter_menu())
        header_box.append(filter_btn)

        self._sort_btn = Gtk.MenuButton()
        self._sort_btn.set_icon_name("view-sort-ascending-symbolic")
        self._sort_btn.set_tooltip_text("Sort options")
        self._sort_btn.set_popover(self._build_sort_menu())
        header_box.append(self._sort_btn)

        self._display_btn = Gtk.MenuButton()
        self._display_btn.set_tooltip_text("Display mode")
        self._display_btn.set_popover(self._build_display_menu())
        header_box.append(self._display_btn)

        batch_btn = Gtk.MenuButton()
        batch_btn.set_icon_name("edit-select-all-symbolic")
        batch_btn.set_tooltip_text("Batch actions for filtered results")
        batch_btn.set_popover(self._build_batch_menu())
        header_box.append(batch_btn)

        dl_btn = Gtk.Button(icon_name="folder-download-symbolic")
        dl_btn.set_tooltip_text("Show Downloads")
        if self._on_show_downloads:
            dl_btn.connect("clicked", lambda *_: self._on_show_downloads())
        header_box.append(dl_btn)

        self.append(header_box)

        self._info_label = Gtk.Label()
        self._info_label.set_xalign(0)
        self._info_label.set_margin_start(16)
        self._info_label.set_margin_end(16)
        self._info_label.set_margin_bottom(6)
        self._info_label.add_css_class("dim-label")
        self._set_info("Configure filters, sort, and display. Preferences are saved per category.")
        self.append(self._info_label)

        # Category tabs
        self._tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._tab_bar.add_css_class("linked")
        self._tab_bar.set_margin_start(16)
        self._tab_bar.set_margin_end(16)
        self._tab_bar.set_margin_bottom(4)
        self._tab_scroll = Gtk.ScrolledWindow()
        self._tab_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self._tab_scroll.set_child(self._tab_bar)
        self.append(self._tab_scroll)

        self.append(Gtk.Separator())

        # Content stack
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.append(self._stack)

        self._loading = LoadingSpinner("Loading library...")
        self._stack.add_named(self._loading, "loading")

        self._empty = EmptyState(
            "bookmarks-symbolic",
            "Your library is empty",
            "Browse manga and add them to your library",
        )
        self._stack.add_named(self._empty, "empty")

        self._grid = MangaGridView(on_manga_click=self._on_manga_selected)
        self._stack.add_named(self._grid, "grid")

        self._list_view = Gtk.ListBox()
        self._list_view.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_view.add_css_class("boxed-list")
        self._list_view.set_margin_start(16)
        self._list_view.set_margin_end(16)
        self._list_view.set_margin_top(16)
        self._list_view.set_margin_bottom(16)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_vexpand(True)
        list_scroll.set_child(self._list_view)
        self._stack.add_named(list_scroll, "list")

    def _build_filter_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        lbl = Gtk.Label(label="Reading Status")
        lbl.add_css_class("heading")
        lbl.set_halign(Gtk.Align.START)
        box.append(lbl)

        self._status_filters = {}
        for status in ReadingStatus:
            if status == ReadingStatus.NONE:
                continue
            cb = Gtk.CheckButton(label=status.value.replace("_", " ").title())
            cb.connect("toggled", self._on_filter_controls_changed)
            box.append(cb)
            self._status_filters[status] = cb

        box.append(Gtk.Separator())

        self._unread_only_cb = Gtk.CheckButton(label="Unread Only")
        self._unread_only_cb.connect("toggled", self._on_filter_controls_changed)
        box.append(self._unread_only_cb)

        self._downloaded_only_cb = Gtk.CheckButton(label="Downloaded Only")
        self._downloaded_only_cb.connect("toggled", self._on_filter_controls_changed)
        box.append(self._downloaded_only_cb)

        reset_btn = Gtk.Button(label="Reset Filters")
        reset_btn.add_css_class("flat")
        reset_btn.connect("clicked", self._reset_filters)
        box.append(reset_btn)

        pop.set_child(box)
        return pop

    def _build_sort_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        lbl = Gtk.Label(label="Sort By")
        lbl.add_css_class("heading")
        lbl.set_halign(Gtk.Align.START)
        box.append(lbl)

        self._sort_by_buttons = {}
        first = None
        for key, label in SORT_OPTIONS.items():
            cb = Gtk.CheckButton(label=label)
            if first is None:
                first = cb
            else:
                cb.set_group(first)
            cb.connect("toggled", self._on_sort_by_changed, key)
            box.append(cb)
            self._sort_by_buttons[key] = cb

        self._sort_desc_cb = Gtk.CheckButton(label="Descending")
        self._sort_desc_cb.connect("toggled", self._on_sort_desc_changed)
        box.append(Gtk.Separator())
        box.append(self._sort_desc_cb)

        pop.set_child(box)
        return pop

    def _build_display_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        lbl = Gtk.Label(label="Display Mode")
        lbl.add_css_class("heading")
        lbl.set_halign(Gtk.Align.START)
        box.append(lbl)

        self._display_mode_buttons = {}
        first = None
        for key, label in DISPLAY_MODES.items():
            cb = Gtk.CheckButton(label=label)
            if first is None:
                first = cb
            else:
                cb.set_group(first)
            cb.connect("toggled", self._on_display_mode_changed, key)
            box.append(cb)
            self._display_mode_buttons[key] = cb

        pop.set_child(box)
        return pop

    def _build_batch_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        mark_read_btn = Gtk.Button(label="Mark Filtered Chapters Read")
        mark_read_btn.add_css_class("flat")
        mark_read_btn.connect("clicked", lambda *_: self._run_batch_mark_read(pop))
        box.append(mark_read_btn)

        remove_btn = Gtk.Button(label="Remove Filtered from Library")
        remove_btn.add_css_class("flat")
        remove_btn.add_css_class("error")
        remove_btn.connect("clicked", lambda *_: self._run_batch_remove_from_library(pop))
        box.append(remove_btn)

        pop.set_child(box)
        return pop

    def reload(self):
        """Reload manga from database."""
        self._stack.set_visible_child_name("loading")

        def load():
            manga = self._db.get_library(self._current_category)
            cats = self._db.get_categories()
            manga_ids = [m.id for m in manga if m.id is not None]
            downloaded_ids = self._db.get_downloaded_manga_ids(manga_ids)
            GLib.idle_add(self._on_loaded, manga, cats, downloaded_ids)

        threading.Thread(target=load, daemon=True).start()

    def _on_loaded(self, manga, categories, downloaded_ids):
        self._all_manga = manga
        self._downloaded_manga_ids = downloaded_ids
        self._rebuild_category_tabs(categories)
        self._apply_filters()

    def _rebuild_category_tabs(self, categories):
        child = self._tab_bar.get_first_child()
        while child:
            next_c = child.get_next_sibling()
            self._tab_bar.remove(child)
            child = next_c

        btn = Gtk.ToggleButton(label="All")
        btn.set_active(self._current_category is None)
        btn.connect("toggled", self._on_category_tab, None)
        btn.add_css_class("flat")
        self._tab_bar.append(btn)

        for cat in categories:
            b = Gtk.ToggleButton(label=cat.name)
            b.set_active(self._current_category == cat.id)
            b.connect("toggled", self._on_category_tab, cat.id)
            b.add_css_class("flat")
            self._tab_bar.append(b)

    def _on_category_tab(self, btn, category_id):
        if not btn.get_active():
            return
        old_category = self._current_category
        self._persist_preferences_for_category(old_category)
        self._current_category = category_id
        self._prefs = self._load_preferences_for_category(category_id)
        self._sync_controls_from_prefs()
        self.reload()

    def _on_search_changed(self, entry):
        self._search_query = entry.get_text().lower()
        self._apply_filters()

    def _on_filter_controls_changed(self, *_):
        if self._syncing_controls:
            return
        self._prefs.status_filters = [
            status.value
            for status, cb in self._status_filters.items()
            if cb.get_active()
        ]
        self._prefs.unread_only = self._unread_only_cb.get_active()
        self._prefs.downloaded_only = self._downloaded_only_cb.get_active()
        self._persist_current_preferences()
        self._apply_filters()

    def _on_sort_by_changed(self, btn, sort_key):
        if self._syncing_controls or not btn.get_active():
            return
        changed = self._prefs.sort_by != sort_key
        self._prefs.sort_by = sort_key
        if changed and sort_key in ("unread_count", "recently_added", "last_read"):
            self._prefs.sort_desc = True
            self._sync_controls_from_prefs()
        self._persist_current_preferences()
        self._apply_filters()

    def _on_sort_desc_changed(self, btn):
        if self._syncing_controls:
            return
        self._prefs.sort_desc = btn.get_active()
        self._persist_current_preferences()
        self._apply_filters()

    def _on_display_mode_changed(self, btn, mode):
        if self._syncing_controls or not btn.get_active():
            return
        self._prefs.display_mode = mode
        self._update_display_icon()
        self._persist_current_preferences()
        self._update_display()

    def _reset_filters(self, *_):
        self._prefs.status_filters = []
        self._prefs.unread_only = False
        self._prefs.downloaded_only = False
        self._sync_controls_from_prefs()
        self._persist_current_preferences()
        self._apply_filters()

    def _run_batch_mark_read(self, popover):
        popover.popdown()
        manga_ids = [m.id for m in self._filtered_manga if m.id is not None]
        if not manga_ids:
            self._set_info("Batch mark-read skipped: no filtered manga.")
            return
        self._set_info("Marking filtered chapters as read...")

        def run():
            updated = self._db.mark_manga_chapters_read_bulk(manga_ids)
            GLib.idle_add(self._on_batch_done, f"Marked {updated} chapters as read.")

        threading.Thread(target=run, daemon=True).start()

    def _run_batch_remove_from_library(self, popover):
        popover.popdown()
        manga_ids = [m.id for m in self._filtered_manga if m.id is not None]
        if not manga_ids:
            self._set_info("Batch remove skipped: no filtered manga.")
            return
        self._set_info("Removing filtered manga from library...")

        def run():
            removed = self._db.remove_from_library_bulk(manga_ids)
            GLib.idle_add(self._on_batch_done, f"Removed {removed} manga from library.")

        threading.Thread(target=run, daemon=True).start()

    def _on_batch_done(self, message: str):
        self._set_info(message)
        self.reload()

    def _apply_filters(self):
        self._filtered_manga = apply_library_preferences(
            manga_list=self._all_manga,
            prefs=self._prefs,
            search_query=self._search_query,
            downloaded_manga_ids=self._downloaded_manga_ids,
        )
        self._update_display()

    def _update_display(self):
        if not self._filtered_manga:
            if self._search_query:
                self._empty.set_title("No results")
            else:
                self._empty.set_title("Your library is empty")
            self._stack.set_visible_child_name("empty")
            return

        if self._prefs.display_mode == "list":
            self._render_list(self._filtered_manga)
            self._stack.set_visible_child_name("list")
        else:
            self._grid.set_manga(self._filtered_manga)
            self._stack.set_visible_child_name("grid")

    def _render_list(self, manga_list):
        child = self._list_view.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_view.remove(child)
            child = nxt

        for manga in manga_list:
            row = Adw.ActionRow(title=manga.title)
            parts = []
            if manga.author:
                parts.append(manga.author)
            parts.append(f"{manga.chapter_count} chapters")
            parts.append(f"{manga.unread_count} unread")
            if manga.id in self._downloaded_manga_ids:
                parts.append("downloaded")
            row.set_subtitle("  •  ".join(parts))

            icon = Gtk.Image.new_from_icon_name("bookmarks-symbolic")
            row.add_prefix(icon)

            arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
            arrow.add_css_class("dim-label")
            row.add_suffix(arrow)

            row.set_activatable(True)
            row.connect("activated", lambda _r, m=manga: self._on_manga_selected(m) if self._on_manga_selected else None)
            self._list_view.append(row)

    def _sync_controls_from_prefs(self):
        self._syncing_controls = True

        selected_statuses = set(self._prefs.status_filters)
        for status, cb in self._status_filters.items():
            cb.set_active(status.value in selected_statuses)
        self._unread_only_cb.set_active(self._prefs.unread_only)
        self._downloaded_only_cb.set_active(self._prefs.downloaded_only)

        for key, btn in self._sort_by_buttons.items():
            btn.set_active(key == self._prefs.sort_by)
        self._sort_desc_cb.set_active(self._prefs.sort_desc)

        for key, btn in self._display_mode_buttons.items():
            btn.set_active(key == self._prefs.display_mode)
        self._update_display_icon()

        self._syncing_controls = False

    def _update_display_icon(self):
        if self._prefs.display_mode == "list":
            self._display_btn.set_icon_name("view-list-symbolic")
        else:
            self._display_btn.set_icon_name("view-grid-symbolic")

    def _prefs_key_for_category(self, category_id):
        if category_id is None:
            return "library_prefs_global"
        return f"library_prefs_category_{category_id}"

    def _load_preferences_for_category(self, category_id):
        key = self._prefs_key_for_category(category_id)
        raw = self._db.get_setting(key, "")
        if raw:
            return LibraryPreferences.from_json(raw)
        if category_id is not None:
            fallback = self._db.get_setting("library_prefs_global", "")
            if fallback:
                return LibraryPreferences.from_json(fallback)
        return LibraryPreferences()

    def _persist_preferences_for_category(self, category_id):
        if category_id is None and self._prefs is None:
            return
        self._db.set_setting(self._prefs_key_for_category(category_id), self._prefs.to_json())

    def _persist_current_preferences(self):
        self._persist_preferences_for_category(self._current_category)
        if self._current_category is None:
            self._db.set_setting("library_prefs_global", self._prefs.to_json())

    def _set_info(self, text: str):
        self._info_label.set_text(text)

    def update_manga(self, manga: Manga):
        """Update a specific manga card (e.g. after adding to library)."""
        for i, m in enumerate(self._all_manga):
            if m.id == manga.id:
                self._all_manga[i] = manga
                break
        self._apply_filters()
