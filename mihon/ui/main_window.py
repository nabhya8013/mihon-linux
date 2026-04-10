"""
Main application window with sidebar navigation.
Uses Adw.NavigationSplitView for responsive layout.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, GObject
from ..core.models import Manga, Chapter
from .library import LibraryView
from .browse import BrowseView, SourceCatalogView
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
        # The root is a NavigationView to handle pushing/popping pages
        self._nav_view = Adw.NavigationView()

        # ── Main Page (Tabs) ───────────────────────────────────────────────
        self._tab_stack = Adw.ViewStack()
        self._tab_stack.connect("notify::visible-child-name", self._on_tab_changed)

        # Setup ToolbarView with ViewSwitcherBar at the bottom
        toolbar_view = Adw.ToolbarView()
        toolbar_view.set_content(self._tab_stack)

        # Top HeaderBar with ViewSwitcherTitle
        header = Adw.HeaderBar()
        self._switcher_title = Adw.ViewSwitcherTitle()
        self._switcher_title.set_title("Mihon")
        self._switcher_title.set_stack(self._tab_stack)
        header.set_title_widget(self._switcher_title)
        toolbar_view.add_top_bar(header)

        # Bottom ViewSwitcherBar for mobile/narrow widths
        switcher_bar = Adw.ViewSwitcherBar()
        switcher_bar.set_stack(self._tab_stack)
        toolbar_view.add_bottom_bar(switcher_bar)

        # Bind the title widget to the bottom bar reveal state (Standard Adwaita pattern)
        # When the title widget is squeezed, the bottom bar is revealed.
        self._switcher_title.bind_property(
            "title-visible",
            switcher_bar,
            "reveal",
            GObject.BindingFlags.SYNC_CREATE
        )

        self._main_nav_page = Adw.NavigationPage.new(toolbar_view, "Mihon")
        self._main_nav_page.set_tag("main")
        self._nav_view.add(self._main_nav_page)

        # ── Tab Content ────────────────────────────────────────────────────
        
        # 1. Library
        self._library_view = LibraryView(
            on_manga_selected=self._show_manga_detail,
            on_show_downloads=self._switch_to_downloads
        )
        self._tab_stack.add_titled_with_icon(self._library_view, "library", "Library", "library-symbolic")

        # 2. Updates (Placeholder)
        self.updates_placeholder = Gtk.Box()
        lbl = Gtk.Label(label="Updates (Coming Soon)", hexpand=True, vexpand=True)
        lbl.add_css_class("dim-label")
        self.updates_placeholder.append(lbl)
        self._tab_stack.add_titled_with_icon(self.updates_placeholder, "updates", "Updates", "view-refresh-symbolic")

        # 3. History
        self._history_view = self._build_history_view()
        self._tab_stack.add_titled_with_icon(self._history_view, "history", "History", "clock-symbolic")

        # 4. Browse
        self._browse_view = BrowseView(
            on_source_selected=self._show_source_catalog,
            on_manga_selected=self._show_manga_detail
        )
        self._tab_stack.add_titled_with_icon(self._browse_view, "browse", "Browse", "find-location-symbolic")

        # 5. More (Settings & Downloads)
        self._more_view = self._build_more_view()
        self._tab_stack.add_titled_with_icon(self._more_view, "more", "More", "more-symbolic")

        # ── Push Pages ─────────────────────────────────────────────────────
        self._detail_view = MangaDetailView(
            on_read_chapter=self._show_reader,
            on_back=self._pop_to_main,
        )
        self._detail_page = Adw.NavigationPage.new(self._detail_view, "Detail")
        self._detail_page.set_tag("detail")
        self._nav_view.add(self._detail_page)

        self._reader_view = ReaderView(on_close=self._pop_to_detail)
        self._reader_page = Adw.NavigationPage.new(self._reader_view, "Reader")
        self._reader_page.set_tag("reader")
        self._nav_view.add(self._reader_page)

        self.set_content(self._nav_view)

    def _on_tab_changed(self, stack, param):
        current = stack.get_visible_child_name()
        if current == "library":
            self._library_view.reload()
        elif current == "history":
            self._refresh_history()
        elif current == "more":
            self._refresh_downloads()

    # ── Navigation ─────────────────────────────────────────────────────────

    def _show_source_catalog(self, extension):
        catalog = SourceCatalogView(
            extension=extension,
            on_manga_selected=self._show_manga_detail,
            on_back=self._pop_to_main
        )
        page = Adw.NavigationPage.new(catalog, extension.name)
        self._nav_view.push(page)

    def _show_manga_detail(self, manga: Manga):
        self._detail_view.load_manga(manga)
        # Pop back to a safe point before pushing the detail singleton page.
        # If we're deeper than main (e.g. on a catalog page), pop to main first.
        try:
            self._nav_view.pop_to_tag("main")
        except Exception:
            pass
        try:
            self._nav_view.push(self._detail_page)
        except Exception:
            pass

    def _show_reader(self, manga: Manga, chapter):
        self._reader_view.load_chapter(manga, chapter)
        # Ensure we're on the detail page before pushing reader
        try:
            self._nav_view.pop_to_tag("detail")
        except Exception:
            pass
        try:
            self._nav_view.push(self._reader_page)
        except Exception:
            pass

    def _pop_to_main(self):
        try:
            self._nav_view.pop_to_tag("main")
        except Exception:
            self._nav_view.pop()

    def _pop_to_detail(self):
        try:
            self._nav_view.pop_to_tag("detail")
        except Exception:
            self._nav_view.pop()

    def _switch_to_downloads(self):
        self._tab_stack.set_visible_child_name("more")

    # ── History view ───────────────────────────────────────────────────────

    def _build_history_view(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        self._history_list = Gtk.ListBox()
        self._history_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._history_list.connect("row-activated", self._on_history_row_activated)
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
            row.set_activatable(True)
            row._history_item = item  # attach item
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

            del_btn = Gtk.Button(icon_name="user-trash-symbolic")
            del_btn.add_css_class("flat")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.connect("clicked", lambda *_, hid=item["id"]: self._delete_history(hid))
            h_box.append(del_btn)

            row.set_child(h_box)
            self._history_list.append(row)

    def _on_history_row_activated(self, listbox, row):
        item = getattr(row, "_history_item", None)
        if item:
            from ..core.database import get_db
            manga = get_db().get_manga_by_id(item["manga_id"])
            if manga:
                self._show_manga_detail(manga)
            listbox.unselect_row(row)

    def _delete_history(self, history_id):
        from ..core.database import get_db
        get_db().delete_history_item(history_id)
        self._refresh_history()

    # ── More (Settings & Downloads) view ───────────────────────────────────

    def _build_more_view(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(32)
        content.set_margin_end(32)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_hexpand(True)
        content.set_halign(Gtk.Align.FILL)

        # Downloads group
        dl_group = Adw.PreferencesGroup(title="Downloads")
        content.append(dl_group)

        self._downloads_list = Gtk.ListBox()
        self._downloads_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._downloads_list.add_css_class("boxed-list")
        dl_group.add(self._downloads_list)

        dl_path_row = Adw.ActionRow(title="Download Location")
        dl_path_row.set_subtitle(str(__import__("pathlib").Path.home() / ".local" / "share" / "mihon-linux" / "downloads"))
        dl_group.add(dl_path_row)

        # Reader settings group
        reader_group = Adw.PreferencesGroup(title="Reader")
        content.append(reader_group)

        dir_row = Adw.ComboRow(title="Default Reading Direction")
        dir_model = Gtk.StringList.new(["Right to Left (RTL)", "Left to Right (LTR)", "Vertical", "Webtoon"])
        dir_row.set_model(dir_model)
        dir_row.set_selected(0)
        reader_group.add(dir_row)

        layout_row = Adw.ComboRow(title="Page Layout")
        layout_model = Gtk.StringList.new(["Single Page", "Double Page"])
        layout_row.set_model(layout_model)
        reader_group.add(layout_row)

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

        # About group
        about_group = Adw.PreferencesGroup(title="About")
        content.append(about_group)

        about_row = Adw.ActionRow(title="Mihon for Linux")
        about_row.set_subtitle("Version 1.0.0 – Built with GTK4 + Python")
        about_group.add(about_row)

        scroll.set_child(content)
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
            lbl.set_margin_top(16)
            lbl.set_margin_bottom(16)
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
