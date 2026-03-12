"""
Library view - shows manga in the user's library with categories.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib
import threading
from ..core.database import get_db
from ..core.models import Manga, ReadingStatus
from .widgets import MangaGridView, EmptyState, LoadingSpinner


class LibraryView(Gtk.Box):
    """
    Main library page showing manga in user's collection.
    Has category tabs, search, and filter controls.
    """

    def __init__(self, on_manga_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_manga_selected = on_manga_selected
        self._all_manga = []
        self._filtered_manga = []
        self._search_query = ""
        self._current_category = None  # None = All

        self._build_ui()
        self.reload()

    def _build_ui(self):
        # Header bar area with search
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.set_margin_start(16)
        header_box.set_margin_end(16)
        header_box.set_margin_top(8)
        header_box.set_margin_bottom(8)

        # Search entry
        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search library...")
        self._search.set_hexpand(True)
        self._search.connect("search-changed", self._on_search_changed)
        header_box.append(self._search)

        # Filter button
        filter_btn = Gtk.MenuButton()
        filter_btn.set_icon_name("funnel-symbolic")
        filter_btn.set_tooltip_text("Filter")
        filter_menu = self._build_filter_menu()
        filter_btn.set_popover(filter_menu)
        header_box.append(filter_btn)

        self.append(header_box)

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

        # Separator
        self.append(Gtk.Separator())

        # Content stack
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.append(self._stack)

        # Loading view
        self._loading = LoadingSpinner("Loading library...")
        self._stack.add_named(self._loading, "loading")

        # Empty state
        self._empty = EmptyState(
            "bookmarks-symbolic",
            "Your library is empty",
            "Browse manga and add them to your library"
        )
        self._stack.add_named(self._empty, "empty")

        # Grid view
        self._grid = MangaGridView(on_manga_click=self._on_manga_selected)
        self._stack.add_named(self._grid, "grid")

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
            cb.connect("toggled", lambda *_: self._apply_filters())
            box.append(cb)
            self._status_filters[status] = cb

        pop.set_child(box)
        return pop

    def reload(self):
        """Reload manga from database."""
        self._stack.set_visible_child_name("loading")
        db = get_db()

        def load():
            manga = db.get_library(self._current_category)
            cats = db.get_categories()
            GLib.idle_add(self._on_loaded, manga, cats)

        threading.Thread(target=load, daemon=True).start()

    def _on_loaded(self, manga, categories):
        self._all_manga = manga
        self._rebuild_category_tabs(categories)
        self._apply_filters()

    def _rebuild_category_tabs(self, categories):
        # Clear existing tabs
        child = self._tab_bar.get_first_child()
        while child:
            next_c = child.get_next_sibling()
            self._tab_bar.remove(child)
            child = next_c

        # "All" tab
        btn = Gtk.ToggleButton(label="All")
        btn.set_active(self._current_category is None)
        btn.connect("toggled", self._on_category_tab, None)
        btn.add_css_class("flat")
        self._tab_bar.append(btn)
        self._category_all_btn = btn

        for cat in categories:
            b = Gtk.ToggleButton(label=cat.name)
            b.set_active(self._current_category == cat.id)
            b.connect("toggled", self._on_category_tab, cat.id)
            b.add_css_class("flat")
            self._tab_bar.append(b)

    def _on_category_tab(self, btn, category_id):
        if not btn.get_active():
            return
        self._current_category = category_id
        self.reload()

    def _on_search_changed(self, entry):
        self._search_query = entry.get_text().lower()
        self._apply_filters()

    def _apply_filters(self):
        manga = self._all_manga
        if self._search_query:
            manga = [
                m for m in manga
                if self._search_query in m.title.lower()
                or self._search_query in m.author.lower()
            ]
        # Status filters
        active_statuses = [
            s for s, cb in self._status_filters.items()
            if cb.get_active()
        ]
        if active_statuses:
            manga = [m for m in manga if m.reading_status in active_statuses]

        self._filtered_manga = manga
        self._update_display()

    def _update_display(self):
        if not self._filtered_manga:
            if self._search_query:
                self._empty.set_title("No results")
                self._stack.set_visible_child_name("empty")
            else:
                self._empty.set_title("Your library is empty")
                self._stack.set_visible_child_name("empty")
        else:
            self._grid.set_manga(self._filtered_manga)
            self._stack.set_visible_child_name("grid")

    def update_manga(self, manga: Manga):
        """Update a specific manga card (e.g. after adding to library)."""
        for i, m in enumerate(self._all_manga):
            if m.id == manga.id:
                self._all_manga[i] = manga
                break
        self._apply_filters()
