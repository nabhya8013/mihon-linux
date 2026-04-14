"""
Browse/Explore view — mirrors the Android Mihon Browse tab with two sections:
  1. Sources — list of installed sources to browse manga from
  2. Extensions — manage/install Tachiyomi APK extensions
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio
import threading
from ..core.models import SearchFilter
from ..core.database import get_db
from ..extensions.registry import get_registry
from .widgets import MangaGridView, EmptyState, LoadingSpinner


class BrowseView(Gtk.Box):
    """
    The main Browse tab content.
    Contains a ViewStack with 'Sources' and 'Extensions' tabs
    matching Mihon Android's Browse layout.
    """

    def __init__(self, on_source_selected=None, on_manga_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_source_selected = on_source_selected
        self._on_manga_selected = on_manga_selected
        self._build_ui()

    def _build_ui(self):
        # ── Tab Switcher ──────────────────────────────────────────────────
        self._view_stack = Adw.ViewStack()

        # Nested ToolbarView for the inline tab bar at top
        tab_bar = Adw.ViewSwitcher()
        tab_bar.set_stack(self._view_stack)
        tab_bar.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        tab_bar.set_margin_start(16)
        tab_bar.set_margin_end(16)
        tab_bar.set_margin_top(8)
        tab_bar.set_margin_bottom(8)
        self.append(tab_bar)
        self.append(Gtk.Separator())

        # ── Sources Tab ───────────────────────────────────────────────────
        sources_page = self._build_sources_tab()
        self._view_stack.add_titled_with_icon(sources_page, "sources", "Sources", "folder-publicshare-symbolic")

        # ── Extensions Tab ────────────────────────────────────────────────
        extensions_page = self._build_extensions_tab()
        self._view_stack.add_titled_with_icon(extensions_page, "extensions", "Extensions", "application-x-addon-symbolic")

        # ── Migrate Tab ───────────────────────────────────────────────────
        migrate_page = self._build_migrate_tab()
        self._view_stack.add_titled_with_icon(migrate_page, "migrate", "Migrate", "system-search-symbolic")

        self._view_stack.set_visible_child_name("sources")

        # Content fills remaining space
        self._view_stack.set_vexpand(True)
        self.append(self._view_stack)

    # ══════════════════════════════════════════════════════════════════════
    #  SOURCES TAB
    # ══════════════════════════════════════════════════════════════════════

    def _build_sources_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        # Sources group
        self._sources_group = Adw.PreferencesGroup(title="Installed Sources")
        self._sources_group.set_description("Tap a source to browse its catalog")
        box.append(self._sources_group)

        self._sources_list = Gtk.ListBox()
        self._sources_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._sources_list.add_css_class("boxed-list")
        self._sources_group.add(self._sources_list)

        scroll.set_child(box)
        self._load_sources()
        return scroll

    def _load_sources(self):
        # Clear existing
        child = self._sources_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._sources_list.remove(child)
            child = nxt

        registry = get_registry()
        extensions = registry.get_all()

        if not extensions:
            row = Adw.ActionRow(title="No sources installed")
            row.set_subtitle("Install extensions from the Extensions tab")
            self._sources_list.append(row)
            return

        for ext in extensions:
            row = Adw.ActionRow(title=ext.name)
            row.set_subtitle(ext.info.description or ext.info.language.upper())

            # Source type icon
            is_jvm = ext.info.id.startswith("jvm_")
            icon_name = "application-x-addon-symbolic" if is_jvm else "folder-publicshare-symbolic"
            icon = Gtk.Image.new_from_icon_name(icon_name)
            row.add_prefix(icon)

            # Language badge
            lang_label = Gtk.Label(label=ext.info.language.upper())
            lang_label.add_css_class("caption")
            lang_label.add_css_class("dim-label")
            lang_label.set_valign(Gtk.Align.CENTER)
            row.add_suffix(lang_label)

            # Navigate arrow
            arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
            arrow.add_css_class("dim-label")
            row.add_suffix(arrow)

            row.set_activatable(True)
            row.connect("activated", lambda r, e=ext: self._on_source_selected(e) if self._on_source_selected else None)
            self._sources_list.append(row)

    def reload_sources(self):
        """Rebuild the sources list (call after installing an extension)."""
        self._load_sources()

    # ══════════════════════════════════════════════════════════════════════
    #  EXTENSIONS TAB
    # ══════════════════════════════════════════════════════════════════════

    def _build_extensions_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        # ── Install Section ───────────────────────────────────────────────
        install_group = Adw.PreferencesGroup(title="Install Extension")
        install_group.set_description("Install Tachiyomi-compatible extensions from APK files")

        install_row = Adw.ActionRow(title="Install from file…")
        install_row.set_subtitle("Select a Tachiyomi extension APK")
        install_icon = Gtk.Image.new_from_icon_name("document-open-symbolic")
        install_row.add_prefix(install_icon)
        install_btn = Gtk.Button(icon_name="list-add-symbolic")
        install_btn.add_css_class("flat")
        install_btn.set_valign(Gtk.Align.CENTER)
        install_btn.connect("clicked", self._on_install_apk_clicked)
        install_row.add_suffix(install_btn)
        install_row.set_activatable_widget(install_btn)
        install_group.add(install_row)

        box.append(install_group)

        # ── Built-in Extensions ───────────────────────────────────────────
        builtin_group = Adw.PreferencesGroup(title="Built-in")
        builtin_group.set_description("Native extensions bundled with Mihon Linux")
        box.append(builtin_group)

        self._builtin_list = Gtk.ListBox()
        self._builtin_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._builtin_list.add_css_class("boxed-list")
        builtin_group.add(self._builtin_list)

        # ── JVM Extensions ────────────────────────────────────────────────
        jvm_group = Adw.PreferencesGroup(title="Tachiyomi Extensions")
        jvm_group.set_description("Extensions loaded from APK files via the JVM bridge")
        box.append(jvm_group)

        self._jvm_list = Gtk.ListBox()
        self._jvm_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._jvm_list.add_css_class("boxed-list")
        jvm_group.add(self._jvm_list)

        self._jvm_empty = Adw.ActionRow(title="No extensions installed")
        self._jvm_empty.set_subtitle("Use 'Install from file' above to add Tachiyomi APK extensions")
        self._jvm_list.append(self._jvm_empty)

        scroll.set_child(box)
        self._load_extensions()
        return scroll

    # ══════════════════════════════════════════════════════════════════════
    #  MIGRATE TAB
    # ══════════════════════════════════════════════════════════════════════

    def _build_migrate_tab(self) -> Gtk.Widget:
        self._migrate_searching = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        controls.set_margin_start(16)
        controls.set_margin_end(16)
        controls.set_margin_top(16)
        controls.set_margin_bottom(8)

        title = Gtk.Label(label="Find Migration Targets")
        title.add_css_class("title-4")
        title.set_xalign(0)
        controls.append(title)

        help_text = Gtk.Label(
            label=(
                "Search all installed sources for equivalent titles. "
                "Optional query filters: src:<source-name> and id:<source-id>."
            )
        )
        help_text.add_css_class("dim-label")
        help_text.set_wrap(True)
        help_text.set_xalign(0)
        controls.append(help_text)

        self._migrate_reference_entry = Gtk.Entry()
        self._migrate_reference_entry.set_placeholder_text("Reference title (optional)")
        controls.append(self._migrate_reference_entry)

        query_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._migrate_query_entry = Gtk.SearchEntry()
        self._migrate_query_entry.set_placeholder_text("Search query (supports src: and id:)")
        self._migrate_query_entry.set_hexpand(True)
        self._migrate_query_entry.connect("activate", self._start_migrate_search)
        query_row.append(self._migrate_query_entry)

        self._migrate_search_btn = Gtk.Button(label="Search Sources")
        self._migrate_search_btn.add_css_class("suggested-action")
        self._migrate_search_btn.connect("clicked", self._start_migrate_search)
        query_row.append(self._migrate_search_btn)
        controls.append(query_row)

        self._migrate_status_label = Gtk.Label(label="Ready to search")
        self._migrate_status_label.add_css_class("dim-label")
        self._migrate_status_label.set_xalign(0)
        controls.append(self._migrate_status_label)

        root.append(controls)
        root.append(Gtk.Separator())

        self._migrate_stack = Gtk.Stack()
        self._migrate_stack.set_vexpand(True)
        self._migrate_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self._migrate_loading = LoadingSpinner("Searching installed sources...")
        self._migrate_stack.add_named(self._migrate_loading, "loading")

        self._migrate_empty = EmptyState(
            "system-search-symbolic",
            "No results yet",
            "Search all sources to find a migration target",
        )
        self._migrate_stack.add_named(self._migrate_empty, "empty")

        self._migrate_results_list = Gtk.ListBox()
        self._migrate_results_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._migrate_results_list.add_css_class("boxed-list")
        self._migrate_results_list.set_margin_start(16)
        self._migrate_results_list.set_margin_end(16)
        self._migrate_results_list.set_margin_top(16)
        self._migrate_results_list.set_margin_bottom(16)
        migrate_scroll = Gtk.ScrolledWindow()
        migrate_scroll.set_vexpand(True)
        migrate_scroll.set_child(self._migrate_results_list)
        self._migrate_stack.add_named(migrate_scroll, "results")

        self._migrate_stack.set_visible_child_name("empty")
        root.append(self._migrate_stack)
        return root

    def _start_migrate_search(self, *_):
        if self._migrate_searching:
            return

        raw_query = self._migrate_query_entry.get_text().strip()
        reference_query = self._migrate_reference_entry.get_text().strip()
        query, src_filter, id_filter = self._parse_migrate_query(raw_query)
        if not query:
            query = reference_query
        if not query:
            self._migrate_empty.set_title("Query required")
            self._migrate_status_label.set_text("Enter a title or search term to find migration candidates.")
            self._migrate_stack.set_visible_child_name("empty")
            return

        sources = self._filter_sources_for_migrate(src_filter, id_filter)
        if not sources:
            self._migrate_empty.set_title("No matching sources")
            self._migrate_status_label.set_text("No installed source matched the src:/id: filters.")
            self._migrate_stack.set_visible_child_name("empty")
            return

        self._migrate_searching = True
        self._migrate_search_btn.set_sensitive(False)
        self._migrate_status_label.set_text(f"Searching {len(sources)} sources...")
        self._migrate_stack.set_visible_child_name("loading")

        def run():
            results = []
            errors = []
            total = len(sources)

            for idx, ext in enumerate(sources, start=1):
                GLib.idle_add(
                    self._migrate_status_label.set_text,
                    f"Searching {idx}/{total}: {ext.name}",
                )
                try:
                    mangas, _has_next = ext.search(SearchFilter(query=query), page=1)
                    for manga in mangas[:20]:
                        if not manga.source_id:
                            manga.source_id = ext.id
                        if not manga.source_manga_id:
                            manga.source_manga_id = manga.url or manga.title
                        results.append((ext, manga))
                except Exception as e:
                    errors.append(f"{ext.name}: {e}")

            deduped = []
            seen = set()
            for ext, manga in results:
                key = (
                    manga.source_id or ext.id,
                    manga.source_manga_id or manga.url or manga.title.lower(),
                )
                if key in seen:
                    continue
                seen.add(key)
                deduped.append((ext, manga))

            deduped.sort(key=lambda item: (item[1].title or "").lower())
            GLib.idle_add(self._on_migrate_search_done, deduped, errors, query)

        threading.Thread(target=run, daemon=True).start()

    def _on_migrate_search_done(self, results, errors, query):
        self._migrate_searching = False
        self._migrate_search_btn.set_sensitive(True)
        self._clear_migrate_results()

        if not results:
            self._migrate_empty.set_title("No migration matches")
            self._migrate_status_label.set_text(f"No source returned matches for '{query}'.")
            self._migrate_stack.set_visible_child_name("empty")
            return

        for ext, manga in results:
            row = Adw.ActionRow(title=manga.title or "Untitled")
            bits = [ext.name]
            if manga.author:
                bits.append(manga.author)
            row.set_subtitle("  •  ".join(bits))

            open_btn = Gtk.Button(icon_name="go-next-symbolic")
            open_btn.add_css_class("flat")
            open_btn.set_tooltip_text("Open details")
            open_btn.connect("clicked", lambda *_btn, m=manga: self._open_migrate_candidate(m))
            row.add_suffix(open_btn)

            add_btn = Gtk.Button(icon_name="list-add-symbolic")
            add_btn.add_css_class("flat")
            add_btn.set_tooltip_text("Add to library")
            add_btn.connect("clicked", lambda *_btn, m=manga: self._add_migrate_candidate_to_library(m))
            row.add_suffix(add_btn)

            row.set_activatable(True)
            row.connect("activated", lambda _row, m=manga: self._open_migrate_candidate(m))
            self._migrate_results_list.append(row)

        if errors:
            self._migrate_status_label.set_text(
                f"Found {len(results)} results ({len(errors)} sources failed)."
            )
        else:
            self._migrate_status_label.set_text(f"Found {len(results)} results.")
        self._migrate_stack.set_visible_child_name("results")

    def _open_migrate_candidate(self, manga):
        if self._on_manga_selected:
            self._on_manga_selected(manga)

    def _add_migrate_candidate_to_library(self, manga):
        try:
            db = get_db()
            manga_id = db.upsert_manga(manga)
            db.add_to_library(manga_id)
            manga.id = manga_id
            manga.in_library = True
            self._migrate_status_label.set_text(
                f"Added '{manga.title}' to library. Open details to verify before removing old source."
            )
        except Exception as e:
            self._migrate_status_label.set_text(f"Failed to add '{manga.title}': {e}")

    def _clear_migrate_results(self):
        child = self._migrate_results_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._migrate_results_list.remove(child)
            child = nxt

    @staticmethod
    def _parse_migrate_query(raw_query: str):
        src_filter = ""
        id_filter = ""
        terms = []
        for token in raw_query.split():
            lower = token.lower()
            if lower.startswith("src:") and len(token) > 4:
                src_filter = token[4:].strip().lower()
            elif lower.startswith("id:") and len(token) > 3:
                id_filter = token[3:].strip().lower()
            else:
                terms.append(token)
        return " ".join(terms).strip(), src_filter, id_filter

    @staticmethod
    def _filter_sources_for_migrate(src_filter: str, id_filter: str):
        sources = get_registry().get_all()
        if id_filter:
            sources = [ext for ext in sources if ext.id.lower() == id_filter]
        if src_filter:
            sources = [
                ext for ext in sources
                if src_filter in ext.name.lower() or src_filter in ext.id.lower()
            ]
        return sources

    def _load_extensions(self):
        """Populate the built-in and JVM extension lists."""
        registry = get_registry()

        # Clear built-in list
        child = self._builtin_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._builtin_list.remove(child)
            child = nxt

        # Clear JVM list
        child = self._jvm_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._jvm_list.remove(child)
            child = nxt

        has_jvm = False
        for ext in registry.get_all():
            is_jvm = ext.info.id.startswith("jvm_")
            if is_jvm:
                has_jvm = True
                self._add_jvm_extension_row(ext)
            else:
                self._add_builtin_extension_row(ext)

        if not has_jvm:
            self._jvm_empty = Adw.ActionRow(title="No extensions installed")
            self._jvm_empty.set_subtitle("Use 'Install from file' above to add Tachiyomi APK extensions")
            self._jvm_list.append(self._jvm_empty)

    def _add_builtin_extension_row(self, ext):
        row = Adw.ActionRow(title=ext.name)
        row.set_subtitle(f"v{ext.info.version} • {ext.info.language.upper()}")

        icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        icon.add_css_class("success")
        row.add_prefix(icon)

        badge = Gtk.Label(label="BUILT-IN")
        badge.add_css_class("caption")
        badge.add_css_class("dim-label")
        badge.set_valign(Gtk.Align.CENTER)
        row.add_suffix(badge)

        self._builtin_list.append(row)

    def _add_jvm_extension_row(self, ext):
        row = Adw.ActionRow(title=ext.name)
        row.set_subtitle(f"v{ext.info.version} • {ext.info.language.upper()} • JVM")

        icon = Gtk.Image.new_from_icon_name("application-x-addon-symbolic")
        row.add_prefix(icon)

        # Uninstall button
        uninstall_btn = Gtk.Button(icon_name="user-trash-symbolic")
        uninstall_btn.add_css_class("flat")
        uninstall_btn.add_css_class("error")
        uninstall_btn.set_valign(Gtk.Align.CENTER)
        uninstall_btn.set_tooltip_text("Uninstall")
        uninstall_btn.connect("clicked", lambda *_, eid=ext.info.id: self._on_uninstall(eid))
        row.add_suffix(uninstall_btn)

        self._jvm_list.append(row)

    # ── Actions ───────────────────────────────────────────────────────────

    def _on_install_apk_clicked(self, *_):
        """Open a file chooser dialog to select an APK."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Select Tachiyomi Extension APK")

        apk_filter = Gtk.FileFilter()
        apk_filter.set_name("APK files")
        apk_filter.add_pattern("*.apk")

        filter_model = Gio.ListStore(item_type=Gtk.FileFilter)
        filter_model.append(apk_filter)
        dialog.set_filters(filter_model)
        dialog.set_default_filter(apk_filter)

        # Get the toplevel window
        window = self.get_root()
        dialog.open(window, None, self._on_apk_file_selected)

    def _on_apk_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                apk_path = file.get_path()
                self._install_apk(apk_path)
        except Exception as e:
            if "Dismissed" not in str(e):
                print(f"[browse] File dialog error: {e}")

    def _install_apk(self, apk_path: str):
        """Install an APK extension in a background thread."""
        # Show a toast
        window = self.get_root()

        def do_install():
            try:
                from ..extensions.extension_manager import get_extension_manager
                manager = get_extension_manager()
                proxies = manager.install_from_apk(apk_path)
                if proxies:
                    # Register all proxies in the registry
                    registry = get_registry()
                    for proxy in proxies:
                        registry.register(proxy)
                    GLib.idle_add(self._on_install_success, [p.name for p in proxies])
                else:
                    GLib.idle_add(self._on_install_error, "Installation failed — check the APK file")
            except Exception as e:
                GLib.idle_add(self._on_install_error, str(e))

        threading.Thread(target=do_install, daemon=True).start()

    def _on_install_success(self, names):
        self._load_extensions()
        self._load_sources()
        window = self.get_root()
        if isinstance(window, Adw.ApplicationWindow):
            toast = Adw.Toast(title=f"Installed: {', '.join(names)}")
            toast.set_timeout(3)
            # Try to find the toast overlay
            try:
                window.get_content().add_toast(toast)
            except Exception:
                pass
        print(f"[browse] Installed extensions: {', '.join(names)}")

    def _on_install_error(self, message):
        window = self.get_root()
        if isinstance(window, Adw.ApplicationWindow):
            toast = Adw.Toast(title=f"Install failed: {message}")
            toast.set_timeout(5)
            try:
                window.get_content().add_toast(toast)
            except Exception:
                pass
        print(f"[browse] Install error: {message}")

    def _on_uninstall(self, extension_id: str):
        """Uninstall a JVM extension."""
        registry = get_registry()
        registry.unregister(extension_id)
        self._load_extensions()
        self._load_sources()


class SourceCatalogView(Gtk.Box):
    """
    Shows Popular, Latest, and allows searching within a specific source.
    Pushed onto the Navigation Stack when a source is selected.
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
        self._load_more_btn.set_label("Load More")
        self._load_more_btn.set_sensitive(True)
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
        self._load_more_btn.set_label("Load More")
        self._load_more_btn.set_sensitive(True)
        self._stack.set_visible_child_name("empty")
        print(f"[source_catalog] Error: {message}")

    def _load_more(self, *_):
        if self._loading_more or not self._has_next:
            return
        self._loading_more = True
        self._load_more_btn.set_label("Loading...")
        self._load_more_btn.set_sensitive(False)
        self._load_page(self._current_page + 1)
