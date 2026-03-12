"""
Main application window with sidebar navigation.
Uses Adw.NavigationSplitView for responsive layout.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib
from ..core.models import Manga, Chapter
from .library import LibraryView
from .browse import BrowseView
from .manga_detail import MangaDetailView
from .reader import ReaderView


class MainWindow(Adw.ApplicationWindow):

    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Mihon")
        self.set_default_size(1280, 800)
        self.set_size_request(800, 600)

        self._navigation_stack = []  # For back navigation
        self._build_ui()

    def _build_ui(self):
        # Root: outer box
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # ── Sidebar ────────────────────────────────────────────────────────
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_size_request(220, -1)
        sidebar.add_css_class("sidebar")

        # App header in sidebar
        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_show_end_title_buttons(False)
        sidebar_header.set_show_start_title_buttons(False)
        sidebar_title = Adw.WindowTitle(title="Mihon")
        sidebar_header.set_title_widget(sidebar_title)
        sidebar.append(sidebar_header)

        # Nav list
        self._nav_list = Gtk.ListBox()
        self._nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._nav_list.add_css_class("navigation-sidebar")
        self._nav_list.connect("row-selected", self._on_nav_selected)

        nav_items = [
            ("library-symbolic", "Library"),
            ("find-location-symbolic", "Browse"),
            ("clock-symbolic", "History"),
            ("arrow-down-symbolic", "Downloads"),
            ("preferences-system-symbolic", "Settings"),
        ]

        self._nav_rows = []
        for icon_name, label in nav_items:
            row = self._make_nav_row(icon_name, label)
            self._nav_list.append(row)
            self._nav_rows.append(row)

        sidebar.append(self._nav_list)
        outer.append(sidebar)

        # Separator
        outer.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # ── Content area ───────────────────────────────────────────────────
        self._content_stack = Gtk.Stack()
        self._content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._content_stack.set_hexpand(True)
        self._content_stack.set_vexpand(True)

        # Library
        self._library_view = LibraryView(on_manga_selected=self._show_manga_detail)
        self._content_stack.add_named(self._library_view, "library")

        # Browse
        self._browse_view = BrowseView(on_manga_selected=self._show_manga_detail)
        self._content_stack.add_named(self._browse_view, "browse")

        # History
        self._history_view = self._build_history_view()
        self._content_stack.add_named(self._history_view, "history")

        # Downloads
        self._downloads_view = self._build_downloads_view()
        self._content_stack.add_named(self._downloads_view, "downloads")

        # Settings
        self._settings_view = self._build_settings_view()
        self._content_stack.add_named(self._settings_view, "settings")

        # Manga detail (pushed on top)
        self._detail_view = MangaDetailView(
            on_read_chapter=self._show_reader,
            on_back=self._pop_to_main,
        )
        self._content_stack.add_named(self._detail_view, "detail")

        # Reader (full screen)
        self._reader_view = ReaderView(on_close=self._pop_to_detail)
        self._content_stack.add_named(self._reader_view, "reader")

        outer.append(self._content_stack)

        self.set_content(outer)

        # Select Library by default
        self._nav_list.select_row(self._nav_rows[0])

    def _make_nav_row(self, icon_name: str, label: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(10)
        box.set_margin_bottom(10)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(20)
        box.append(icon)

        lbl = Gtk.Label(label=label)
        lbl.set_hexpand(True)
        lbl.set_xalign(0)
        box.append(lbl)

        row.set_child(box)
        row._page_name = label.lower()
        return row

    def _on_nav_selected(self, listbox, row):
        if not row:
            return
        # Guard: don't let sidebar selection override detail/reader views
        current = self._content_stack.get_visible_child_name()
        if current in ("detail", "reader"):
            return
        page = row._page_name
        self._content_stack.set_visible_child_name(page)
        if page == "library":
            self._library_view.reload()
        elif page == "history":
            self._refresh_history()
        elif page == "downloads":
            self._refresh_downloads()

    # ── Navigation ─────────────────────────────────────────────────────────

    def _show_manga_detail(self, manga: Manga):
        self._navigation_stack.append(
            self._content_stack.get_visible_child_name()
        )
        self._detail_view.load_manga(manga)
        self._content_stack.set_visible_child_name("detail")

    def _show_reader(self, manga: Manga, chapter):
        self._navigation_stack.append("detail")
        self._reader_view.load_chapter(manga, chapter)
        self._content_stack.set_visible_child_name("reader")

    def _pop_to_main(self):
        prev = self._navigation_stack.pop() if self._navigation_stack else "library"
        if prev in ("library", "browse", "history", "downloads", "settings"):
            self._content_stack.set_visible_child_name(prev)
            # Re-sync sidebar
            page_map = {"library": 0, "browse": 1, "history": 2, "downloads": 3, "settings": 4}
            idx = page_map.get(prev, 0)
            self._nav_list.select_row(self._nav_rows[idx])
        else:
            self._content_stack.set_visible_child_name(prev)

    def _pop_to_detail(self):
        self._content_stack.set_visible_child_name("detail")
        if self._navigation_stack:
            self._navigation_stack.pop()

    # ── History view ───────────────────────────────────────────────────────

    def _build_history_view(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="History"))
        box.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        self._history_list = Gtk.ListBox()
        self._history_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._history_list.add_css_class("boxed-list")
        self._history_list.set_margin_start(16)
        self._history_list.set_margin_end(16)
        self._history_list.set_margin_top(16)
        self._history_list.set_margin_bottom(16)

        scroll.set_child(self._history_list)
        box.append(scroll)
        return box

    def _refresh_history(self):
        from ..core.database import get_db
        from datetime import datetime

        child = self._history_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._history_list.remove(child)
            child = nxt

        history = get_db().get_history(limit=100)
        if not history:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label="No reading history yet")
            lbl.add_css_class("dim-label")
            lbl.set_margin_top(32)
            lbl.set_margin_bottom(32)
            row.set_child(lbl)
            self._history_list.append(row)
            return

        for item in history:
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            h_box.set_margin_start(12)
            h_box.set_margin_end(12)
            h_box.set_margin_top(8)
            h_box.set_margin_bottom(8)

            txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            txt.set_hexpand(True)
            title = Gtk.Label(label=item["manga_title"])
            title.set_xalign(0)
            title.add_css_class("body")
            txt.append(title)

            ch_info = Gtk.Label(
                label=f"Chapter {item['chapter_number']:g} – {item['chapter_title']}"
                if item['chapter_number'] >= 0 else item['chapter_title']
            )
            ch_info.set_xalign(0)
            ch_info.add_css_class("caption")
            ch_info.add_css_class("dim-label")
            txt.append(ch_info)
            h_box.append(txt)

            dt = datetime.fromtimestamp(item["read_at"]).strftime("%b %d %H:%M")
            date_lbl = Gtk.Label(label=dt)
            date_lbl.add_css_class("caption")
            date_lbl.add_css_class("dim-label")
            h_box.append(date_lbl)

            row.set_child(h_box)
            self._history_list.append(row)

    # ── Downloads view ─────────────────────────────────────────────────────

    def _build_downloads_view(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Downloads"))
        box.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        self._downloads_list = Gtk.ListBox()
        self._downloads_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._downloads_list.add_css_class("boxed-list")
        self._downloads_list.set_margin_start(16)
        self._downloads_list.set_margin_end(16)
        self._downloads_list.set_margin_top(16)
        self._downloads_list.set_margin_bottom(16)

        scroll.set_child(self._downloads_list)
        box.append(scroll)
        return box

    def _refresh_downloads(self):
        from ..core.downloader import get_download_manager

        child = self._downloads_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._downloads_list.remove(child)
            child = nxt

        dm = get_download_manager()
        items = dm.get_queue()
        if not items:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label="No active downloads")
            lbl.add_css_class("dim-label")
            lbl.set_margin_top(32)
            lbl.set_margin_bottom(32)
            row.set_child(lbl)
            self._downloads_list.append(row)
            return

        for item in items:
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.set_margin_start(12)
            box.set_margin_end(12)
            box.set_margin_top(8)
            box.set_margin_bottom(8)

            title = Gtk.Label(
                label=f"{item.manga.title} – Ch.{item.chapter.chapter_number:g}"
            )
            title.set_xalign(0)
            box.append(title)

            progress = Gtk.ProgressBar()
            progress.set_fraction(item.progress)
            progress.set_text(f"{item.pages_downloaded}/{item.total_pages} pages")
            progress.set_show_text(True)
            box.append(progress)

            row.set_child(box)
            self._downloads_list.append(row)

    # ── Settings view ──────────────────────────────────────────────────────

    def _build_settings_view(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Settings"))
        box.append(header)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(32)
        content.set_margin_end(32)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_hexpand(True)
        content.set_halign(Gtk.Align.FILL)

        # Reader settings group
        reader_group = Adw.PreferencesGroup(title="Reader")
        content.append(reader_group)

        # Default reading direction
        dir_row = Adw.ComboRow(title="Default Reading Direction")
        dir_model = Gtk.StringList.new(["Right to Left (RTL)", "Left to Right (LTR)", "Vertical", "Webtoon"])
        dir_row.set_model(dir_model)
        dir_row.set_selected(0)
        reader_group.add(dir_row)

        # Page layout
        layout_row = Adw.ComboRow(title="Page Layout")
        layout_model = Gtk.StringList.new(["Single Page", "Double Page"])
        layout_row.set_model(layout_model)
        reader_group.add(layout_row)

        # Background
        bg_row = Adw.ComboRow(title="Reader Background")
        bg_model = Gtk.StringList.new(["Black", "White", "Gray"])
        bg_row.set_model(bg_model)
        reader_group.add(bg_row)

        # Library group
        lib_group = Adw.PreferencesGroup(title="Library")
        content.append(lib_group)

        update_row = Adw.SwitchRow(title="Auto-update library", subtitle="Check for new chapters on startup")
        lib_group.add(update_row)

        unread_row = Adw.SwitchRow(title="Show unread badge", subtitle="Show unread chapter count on covers")
        unread_row.set_active(True)
        lib_group.add(unread_row)

        # Download group
        dl_group = Adw.PreferencesGroup(title="Downloads")
        content.append(dl_group)

        dl_path_row = Adw.ActionRow(title="Download Location")
        dl_path_row.set_subtitle(str(__import__("pathlib").Path.home() / ".local" / "share" / "mihon-linux" / "downloads"))
        dl_group.add(dl_path_row)

        # About group
        about_group = Adw.PreferencesGroup(title="About")
        content.append(about_group)

        about_row = Adw.ActionRow(title="Mihon for Linux")
        about_row.set_subtitle("Version 1.0.0 – Built with GTK4 + Python")
        about_group.add(about_row)

        scroll.set_child(content)
        box.append(scroll)
        return box
