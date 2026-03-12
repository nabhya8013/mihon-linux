"""
Browse/Explore view - search and browse manga sources.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib
import threading
from ..core.models import SearchFilter
from ..extensions.registry import get_registry
from .widgets import MangaGridView, EmptyState, LoadingSpinner


class BrowseView(Gtk.Box):
    """
    Browse page: shows Popular, Latest, and allows searching manga sources.
    """

    def __init__(self, on_manga_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_manga_selected = on_manga_selected
        self._current_extension = None
        self._current_page = 1
        self._has_next = False
        self._loading_more = False
        self._current_mode = "popular"  # popular | latest | search
        self._search_query = ""
        self._manga_list = []

        self._build_ui()
        self._select_default_extension()

    def _build_ui(self):
        # Top bar: source selector + mode tabs + search
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Source selector row
        source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        source_row.set_margin_start(16)
        source_row.set_margin_end(16)
        source_row.set_margin_top(8)
        source_row.set_margin_bottom(4)

        src_label = Gtk.Label(label="Source:")
        src_label.add_css_class("dim-label")
        source_row.append(src_label)

        self._source_combo = Gtk.DropDown()
        self._source_combo.set_hexpand(True)
        source_row.append(self._source_combo)

        top.append(source_row)

        # Mode tabs: Popular | Latest | Search
        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_box.set_margin_start(16)
        tab_box.set_margin_end(16)
        tab_box.set_margin_bottom(4)
        tab_box.add_css_class("linked")

        self._popular_btn = Gtk.ToggleButton(label="Popular")
        self._popular_btn.set_active(True)
        self._popular_btn.set_hexpand(True)
        self._popular_btn.connect("toggled", self._on_mode_changed, "popular")

        self._latest_btn = Gtk.ToggleButton(label="Latest")
        self._latest_btn.set_group(self._popular_btn)
        self._latest_btn.set_hexpand(True)
        self._latest_btn.connect("toggled", self._on_mode_changed, "latest")

        self._search_btn = Gtk.ToggleButton(label="Search")
        self._search_btn.set_group(self._popular_btn)
        self._search_btn.set_hexpand(True)
        self._search_btn.connect("toggled", self._on_mode_changed, "search")

        tab_box.append(self._popular_btn)
        tab_box.append(self._latest_btn)
        tab_box.append(self._search_btn)
        top.append(tab_box)

        # Search bar (shown only in search mode)
        self._search_revealer = Gtk.Revealer()
        self._search_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)

        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        search_box.set_margin_start(16)
        search_box.set_margin_end(16)
        search_box.set_margin_bottom(8)

        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search manga...")
        self._search_entry.set_hexpand(True)
        self._search_entry.connect("activate", self._on_search_activate)

        search_go = Gtk.Button(label="Go")
        search_go.add_css_class("suggested-action")
        search_go.connect("clicked", self._on_search_activate)

        search_box.append(self._search_entry)
        search_box.append(search_go)
        self._search_revealer.set_child(search_box)
        top.append(self._search_revealer)

        self.append(top)
        self.append(Gtk.Separator())

        # Content stack
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self._loading = LoadingSpinner("Loading manga...")
        self._stack.add_named(self._loading, "loading")

        self._empty = EmptyState(
            "find-location-symbolic",
            "No manga found",
            "Try a different search term or source"
        )
        self._stack.add_named(self._empty, "empty")

        # Grid + load more button
        grid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._grid = MangaGridView(on_manga_click=self._on_manga_selected)
        grid_box.append(self._grid)

        # Load more / pagination row
        self._load_more_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            halign=Gtk.Align.CENTER,
            margin_top=8,
            margin_bottom=16,
        )
        self._load_more_btn = Gtk.Button(label="Load More")
        self._load_more_btn.add_css_class("pill")
        self._load_more_btn.connect("clicked", self._load_more)
        self._load_more_box.append(self._load_more_btn)
        grid_box.append(self._load_more_box)

        self._stack.add_named(grid_box, "grid")
        self.append(self._stack)

    def _select_default_extension(self):
        registry = get_registry()
        extensions = registry.get_all()
        if not extensions:
            return

        # Build source dropdown
        names = [ext.name for ext in extensions]
        str_list = Gtk.StringList.new(names)
        self._source_combo.set_model(str_list)
        self._extensions_list = extensions
        self._source_combo.set_selected(0)
        self._source_combo.connect("notify::selected", self._on_source_changed)

        self._current_extension = extensions[0]
        self._load_page(1)

    def _on_source_changed(self, combo, _):
        idx = combo.get_selected()
        if 0 <= idx < len(self._extensions_list):
            self._current_extension = self._extensions_list[idx]
            self._manga_list = []
            self._load_page(1)

    def _on_mode_changed(self, btn, mode):
        if not btn.get_active():
            return
        self._current_mode = mode
        is_search = (mode == "search")
        self._search_revealer.set_reveal_child(is_search)
        if not is_search:
            self._manga_list = []
            self._load_page(1)

    def _on_search_activate(self, *_):
        self._search_query = self._search_entry.get_text().strip()
        if self._search_query:
            self._manga_list = []
            self._load_page(1)

    def _load_page(self, page: int):
        if not self._current_extension:
            return
        self._current_page = page
        if page == 1:
            self._stack.set_visible_child_name("loading")

        ext = self._current_extension
        mode = self._current_mode
        query = self._search_query

        def fetch():
            try:
                if mode == "popular":
                    results, has_next = ext.get_popular(page)
                elif mode == "latest":
                    results, has_next = ext.get_latest(page)
                else:
                    f = SearchFilter(query=query)
                    results, has_next = ext.search(f, page)
                GLib.idle_add(self._on_results, results, has_next, page)
            except Exception as e:
                GLib.idle_add(self._on_error, str(e))

        threading.Thread(target=fetch, daemon=True).start()

    def _on_results(self, results, has_next, page):
        self._has_next = has_next
        self._loading_more = False
        if page == 1:
            self._manga_list = results
            if results:
                self._grid.set_manga(results)
                self._stack.set_visible_child_name("grid")
            else:
                self._stack.set_visible_child_name("empty")
        else:
            self._manga_list.extend(results)
            self._grid.append_manga(results)

        self._load_more_box.set_visible(has_next)

    def _on_error(self, message):
        self._loading_more = False
        self._stack.set_visible_child_name("empty")
        # Show error toast if possible
        print(f"[browse] Error: {message}")

    def _load_more(self, *_):
        if self._loading_more or not self._has_next:
            return
        self._loading_more = True
        self._load_more_btn.set_label("Loading...")
        self._load_more_btn.set_sensitive(False)
        self._load_page(self._current_page + 1)
        self._load_more_btn.set_label("Load More")
        self._load_more_btn.set_sensitive(True)
