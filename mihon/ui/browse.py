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
    The main Browse tab content. Displays a list of available Sources and Extensions.
    """

    def __init__(self, on_source_selected=None, on_manga_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_source_selected = on_source_selected

        self._build_ui()
        self._load_sources()

    def _build_ui(self):
        # We can implement a tab bar here for "Sources" and "Extensions" later.
        # For now, just a list of installed sources.
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        # Sources group
        self._sources_group = Adw.PreferencesGroup(title="Sources")
        box.append(self._sources_group)

        self._sources_list = Gtk.ListBox()
        self._sources_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._sources_list.add_css_class("boxed-list")
        self._sources_group.add(self._sources_list)

        scroll.set_child(box)
        self.append(scroll)

    def _load_sources(self):
        registry = get_registry()
        extensions = registry.get_all()

        for ext in extensions:
            row = Adw.ActionRow(title=ext.name)
            # Add a cute icon
            icon = Gtk.Image.new_from_icon_name("folder-publicshare-symbolic")
            row.add_prefix(icon)
            row.set_activatable(True)
            row.connect("activated", lambda r, e=ext: self._on_source_selected(e) if self._on_source_selected else None)
            self._sources_list.append(row)


class SourceCatalogView(Gtk.Box):
    """
    Shows Popular, Latest, and allows searching within a specific source.
    Pushed onto the Navigation Stack.
    """

    def __init__(self, extension, on_manga_selected=None, on_back=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._extension = extension
        self._on_manga_selected = on_manga_selected
        self._on_back = on_back

        self._current_page = 1
        self._has_next = False
        self._loading_more = False
        self._current_mode = "popular"  # popular | latest | search
        self._search_query = ""
        self._manga_list = []

        self._build_ui()
        self._load_page(1)

    def _build_ui(self):
        # Header bar with back button
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)
        header.set_title_widget(Adw.WindowTitle(title=self._extension.name))

        back_btn = Gtk.Button(icon_name="go-previous-symbolic")
        back_btn.set_tooltip_text("Back")
        back_btn.connect("clicked", lambda *_: self._on_back() if self._on_back else None)
        header.pack_start(back_btn)

        self.append(header)

        # Mode tabs: Popular | Latest | Search
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_box.set_margin_start(16)
        tab_box.set_margin_end(16)
        tab_box.set_margin_top(8)
        tab_box.set_margin_bottom(8)
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
        self._search_entry.set_placeholder_text(f"Search {self._extension.name}...")
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
            "Try a different search term"
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
        
        # Make the grid scrollable
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self._stack)
        self.append(scroll)

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
        self._current_page = page
        if page == 1:
            self._stack.set_visible_child_name("loading")

        ext = self._extension
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
        print(f"[source_catalog] Error: {message}")

    def _load_more(self, *_):
        if self._loading_more or not self._has_next:
            return
        self._loading_more = True
        self._load_more_btn.set_label("Loading...")
        self._load_more_btn.set_sensitive(False)
        self._load_page(self._current_page + 1)
        self._load_more_btn.set_label("Load More")
        self._load_more_btn.set_sensitive(True)
