"""
Main application window with sidebar navigation.
Uses Adw.NavigationSplitView for responsive layout.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, GObject, Gio, Pango
import threading
import webbrowser
from pathlib import Path
from ..core.models import Manga, Chapter, DownloadStatus
from ..core.http_client import set_challenge_solver
from .library import LibraryView
from .browse import BrowseView, SourceCatalogView
from .updates import UpdatesView
from .manga_detail import MangaDetailView
from .reader import ReaderView
from .challenge_solver import WebKitCookieSolver
from ..core.database import get_db, DOWNLOADS_DIR
from ..core.tracking import get_track_manager
from ..extensions.repo_manager import get_repo_manager
from .notify import notify, notify_error
import logging

logger = logging.getLogger("main_window")


class MainWindow(Adw.ApplicationWindow):

    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Mihon")
        self.set_default_size(1280, 800)
        self.set_size_request(800, 600)

        self._navigation_stack = []  # For back navigation
        self._build_ui()
        self._setup_shortcuts()
        self._challenge_solver = WebKitCookieSolver(self)
        set_challenge_solver(self._challenge_solver.solve)
        GLib.idle_add(self._run_startup_tasks)

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

        # 2. Updates
        self._updates_view = UpdatesView(on_manga_selected=self._show_manga_detail)
        self._tab_stack.add_titled_with_icon(self._updates_view, "updates", "Updates", "view-refresh-symbolic")

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

        # Every toast in the app lands here; mihon.ui.notify finds it by
        # walking up from whichever widget raised the message.
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self._nav_view)
        self.set_content(self.toast_overlay)

    def _on_tab_changed(self, stack, param):
        current = stack.get_visible_child_name()
        if current == "library":
            self._library_view.reload()
        elif current == "updates":
            self._updates_view.ensure_initial_check()
            self._updates_view.refresh_cached()
        elif current == "history":
            self._refresh_history()
        elif current == "more":
            self._refresh_downloads()
            self._start_downloads_refresh_timer()
            return
        self._stop_downloads_refresh_timer()

    def _start_downloads_refresh_timer(self):
        if getattr(self, "_downloads_refresh_source", None) is not None:
            return
        self._downloads_refresh_source = GLib.timeout_add(2000, self._on_downloads_refresh_tick)

    def _stop_downloads_refresh_timer(self):
        source = getattr(self, "_downloads_refresh_source", None)
        if source is not None:
            GLib.source_remove(source)
            self._downloads_refresh_source = None

    def _on_downloads_refresh_tick(self) -> bool:
        self._refresh_downloads()
        return True

    def _run_startup_tasks(self):
        from ..core.database import get_db

        auto_update = get_db().get_setting("auto_update_library", "1") == "1"
        if auto_update:
            self._updates_view.ensure_initial_check()
        return False

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

        self._dl_path_row = Adw.ActionRow(title="Download Location")
        self._dl_path_row.set_subtitle(get_db().get_setting("download_dir", str(DOWNLOADS_DIR)))
        self._dl_path_row.set_subtitle_lines(2)
        dl_choose_btn = Gtk.Button(label="Choose…")
        dl_choose_btn.set_valign(Gtk.Align.CENTER)
        dl_choose_btn.connect("clicked", self._on_choose_download_dir)
        self._dl_path_row.add_suffix(dl_choose_btn)
        self._dl_path_row.set_activatable_widget(dl_choose_btn)
        dl_group.add(self._dl_path_row)

        max_dl_row = Adw.SpinRow.new_with_range(1, 10, 1)
        max_dl_row.set_title("Max simultaneous downloads")
        max_dl_row.set_subtitle("Applies the next time the app starts")
        try:
            current_max = int(get_db().get_setting("max_simultaneous_downloads", "3"))
        except ValueError:
            current_max = 3
        max_dl_row.set_value(current_max)
        max_dl_row.connect("notify::value", self._on_max_downloads_changed)
        dl_group.add(max_dl_row)

        # Reader settings group
        reader_group = Adw.PreferencesGroup(
            title="Reader",
            description="Defaults for new chapters. Changing direction/layout/background from the reader toolbar updates these too.",
        )
        content.append(reader_group)

        db = get_db()

        self._DIRECTION_VALUES = ["rtl", "ltr", "vertical", "webtoon"]
        dir_row = Adw.ComboRow(title="Default Reading Direction")
        dir_model = Gtk.StringList.new(["Right to Left (RTL)", "Left to Right (LTR)", "Vertical", "Webtoon"])
        dir_row.set_model(dir_model)
        current_direction = db.get_setting("reading_direction", "rtl")
        dir_row.set_selected(
            self._DIRECTION_VALUES.index(current_direction)
            if current_direction in self._DIRECTION_VALUES else 0
        )
        dir_row.connect("notify::selected", self._on_default_direction_changed)
        reader_group.add(dir_row)

        self._LAYOUT_VALUES = ["single", "double", "auto"]
        layout_row = Adw.ComboRow(title="Page Layout")
        layout_model = Gtk.StringList.new(["Single Page", "Double Page", "Auto"])
        layout_row.set_model(layout_model)
        current_layout = db.get_setting("page_layout", "single")
        layout_row.set_selected(
            self._LAYOUT_VALUES.index(current_layout)
            if current_layout in self._LAYOUT_VALUES else 0
        )
        layout_row.connect("notify::selected", self._on_default_layout_changed)
        reader_group.add(layout_row)

        self._BG_VALUES = ["black", "white", "gray"]
        bg_row = Adw.ComboRow(title="Reader Background")
        bg_model = Gtk.StringList.new(["Black", "White", "Gray"])
        bg_row.set_model(bg_model)
        current_bg = db.get_setting("reader_background", "black")
        bg_row.set_selected(
            self._BG_VALUES.index(current_bg) if current_bg in self._BG_VALUES else 0
        )
        bg_row.connect("notify::selected", self._on_default_background_changed)
        reader_group.add(bg_row)

        # Library group
        lib_group = Adw.PreferencesGroup(title="Library")
        content.append(lib_group)

        self._auto_update_row = Adw.SwitchRow(
            title="Auto-update library",
            subtitle="Check for new chapters on startup and on a schedule",
        )
        auto_update = get_db().get_setting("auto_update_library", "1") == "1"
        self._auto_update_row.set_active(auto_update)
        self._auto_update_row.connect("notify::active", self._on_auto_update_toggled)
        lib_group.add(self._auto_update_row)

        self._UPDATE_INTERVAL_VALUES = ["0", "6", "12", "24"]
        interval_row = Adw.ComboRow(
            title="Update interval",
            subtitle="How often to check the library in the background",
        )
        interval_row.set_model(Gtk.StringList.new(["Manual only", "Every 6 hours", "Every 12 hours", "Every 24 hours"]))
        current_interval = get_db().get_setting("library_update_interval_hours", "12")
        interval_row.set_selected(
            self._UPDATE_INTERVAL_VALUES.index(current_interval)
            if current_interval in self._UPDATE_INTERVAL_VALUES else 2
        )
        interval_row.connect("notify::selected", self._on_update_interval_changed)
        lib_group.add(interval_row)

        skip_dropped_row = Adw.SwitchRow(
            title="Skip dropped manga in background checks",
            subtitle="The manual Check Updates button always checks everything",
        )
        skip_dropped_row.set_active(get_db().get_setting("smart_update_skip_dropped", "1") == "1")
        skip_dropped_row.connect("notify::active", self._on_skip_dropped_toggled)
        lib_group.add(skip_dropped_row)

        unread_row = Adw.SwitchRow(title="Show unread badge", subtitle="Show unread chapter count on covers")
        unread_row.set_active(get_db().get_setting("show_unread_badge", "1") == "1")
        unread_row.connect("notify::active", self._on_show_unread_badge_toggled)
        lib_group.add(unread_row)

        # Data group: backup / restore
        data_group = Adw.PreferencesGroup(
            title="Data",
            description="Move your library between this app and Mihon on Android.",
        )
        content.append(data_group)

        import_row = Adw.ActionRow(
            title="Import .tachibk backup",
            subtitle="Restore your library, categories, and chapter metadata from an Android Mihon backup file.",
        )
        import_btn = Gtk.Button(label="Choose File…")
        import_btn.add_css_class("suggested-action")
        import_btn.set_valign(Gtk.Align.CENTER)
        import_btn.connect("clicked", self._on_import_tachibk_clicked)
        import_row.add_suffix(import_btn)
        import_row.set_activatable_widget(import_btn)
        data_group.add(import_row)

        export_row = Adw.ActionRow(
            title="Export .tachibk backup",
            subtitle="Write your library, categories, and chapter progress to a file Android Mihon can restore.",
        )
        export_btn = Gtk.Button(label="Save As…")
        export_btn.set_valign(Gtk.Align.CENTER)
        export_btn.connect("clicked", self._on_export_tachibk_clicked)
        export_row.add_suffix(export_btn)
        export_row.set_activatable_widget(export_btn)
        data_group.add(export_row)

        cache_row = Adw.ActionRow(
            title="Clear page cache",
            subtitle="Delete cached chapter images. Covers and downloads are kept.",
        )
        self._cache_size_label = Gtk.Label()
        self._cache_size_label.add_css_class("dim-label")
        self._cache_size_label.set_valign(Gtk.Align.CENTER)
        cache_row.add_suffix(self._cache_size_label)

        clear_cache_btn = Gtk.Button(label="Clear")
        clear_cache_btn.add_css_class("destructive-action")
        clear_cache_btn.set_valign(Gtk.Align.CENTER)
        clear_cache_btn.connect("clicked", self._on_clear_page_cache)
        cache_row.add_suffix(clear_cache_btn)
        data_group.add(cache_row)
        self._refresh_cache_size()

        # Local source
        local_group = Adw.PreferencesGroup(
            title="Local source",
            description=(
                "Read your own CBZ/ZIP archives and image folders. One folder per "
                "series, chapters inside it."
            ),
        )
        content.append(local_group)

        self._local_dir_row = Adw.ActionRow(title="Library folder")
        self._local_dir_row.set_subtitle_lines(2)
        choose_btn = Gtk.Button(label="Choose\u2026")
        choose_btn.set_valign(Gtk.Align.CENTER)
        choose_btn.connect("clicked", self._on_choose_local_dir)
        self._local_dir_row.add_suffix(choose_btn)
        self._local_dir_row.set_activatable_widget(choose_btn)
        local_group.add(self._local_dir_row)

        scan_row = Adw.ActionRow(
            title="Rescan",
            subtitle="Pick up series added to the folder since the app started.",
        )
        scan_btn = Gtk.Button(label="Rescan")
        scan_btn.set_valign(Gtk.Align.CENTER)
        scan_btn.connect("clicked", self._on_rescan_local)
        scan_row.add_suffix(scan_btn)
        local_group.add(scan_row)
        self._refresh_local_dir_row()

        # Extension repositories
        repo_group = Adw.PreferencesGroup(
            title="Extension repositories",
            description=(
                "Sources of installable extensions. Each repository publishes an "
                "index.json listing what it offers."
            ),
        )
        content.append(repo_group)

        self._repo_list_group = repo_group
        self._repo_rows = []

        add_repo_row = Adw.EntryRow(title="Add a repository URL")
        add_repo_row.set_show_apply_button(True)
        add_repo_row.connect("apply", self._on_add_repo)
        repo_group.add(add_repo_row)
        self._add_repo_row = add_repo_row
        self._refresh_repo_rows()

        # Tracking group: per-service client ID and login
        track_group = Adw.PreferencesGroup(
            title="Tracking",
            description=(
                "Keep AniList and MyAnimeList up to date as you read. Each service "
                "needs an API client you create yourself — a desktop app cannot ship "
                "a shared secret."
            ),
        )
        content.append(track_group)
        self._tracking_rows = {}

        manager = get_track_manager()
        for service in manager.services:
            track_group.add(self._build_tracker_row(service))

        self._tracking_queue_row = Adw.ActionRow(
            title="Pending updates",
            subtitle="Tracker updates that could not be sent yet. They retry automatically.",
        )
        self._tracking_queue_label = Gtk.Label()
        self._tracking_queue_label.add_css_class("dim-label")
        self._tracking_queue_label.set_valign(Gtk.Align.CENTER)
        self._tracking_queue_row.add_suffix(self._tracking_queue_label)

        retry_btn = Gtk.Button(label="Retry now")
        retry_btn.set_valign(Gtk.Align.CENTER)
        retry_btn.connect("clicked", self._on_retry_tracking_queue)
        self._tracking_queue_row.add_suffix(retry_btn)
        track_group.add(self._tracking_queue_row)

        storage_row = Adw.ActionRow(title="Token storage")
        storage_label = Gtk.Label(label=getattr(manager, "credentials", None)
                                  and manager.credentials.backend_name or "unknown")
        storage_label.add_css_class("dim-label")
        storage_label.set_valign(Gtk.Align.CENTER)
        storage_row.add_suffix(storage_label)
        if getattr(manager, "credentials", None) and not manager.credentials.uses_keyring:
            storage_row.set_subtitle(
                "No system keyring is available, so tokens are stored unencrypted "
                "in the app database."
            )
        track_group.add(storage_row)
        self._refresh_tracking_queue_label()

        # About group
        about_group = Adw.PreferencesGroup(title="About")
        content.append(about_group)

        about_row = Adw.ActionRow(title="Mihon for Linux")
        about_row.set_subtitle("Version 1.0.0 – Built with GTK4 + Python")
        about_group.add(about_row)

        scroll.set_child(content)
        box.append(scroll)
        return box

    def _on_auto_update_toggled(self, row, _pspec):
        from ..core.database import get_db

        value = "1" if row.get_active() else "0"
        get_db().set_setting("auto_update_library", value)
        self._updates_view.reschedule()

    def _on_update_interval_changed(self, row, _pspec):
        get_db().set_setting(
            "library_update_interval_hours", self._UPDATE_INTERVAL_VALUES[row.get_selected()]
        )
        self._updates_view.reschedule()

    def _on_skip_dropped_toggled(self, row, _pspec):
        value = "1" if row.get_active() else "0"
        get_db().set_setting("smart_update_skip_dropped", value)

    def _on_show_unread_badge_toggled(self, row, _pspec):
        value = "1" if row.get_active() else "0"
        get_db().set_setting("show_unread_badge", value)
        self._library_view.reload()

    def _on_choose_download_dir(self, button):
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose the download folder")
        current = get_db().get_setting("download_dir", str(DOWNLOADS_DIR))
        try:
            dialog.set_initial_folder(Gio.File.new_for_path(current))
        except Exception:
            pass
        dialog.select_folder(self, None, self._on_download_dir_chosen)

    def _on_download_dir_chosen(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
        except Exception as e:
            if "Dismissed" not in str(e):
                notify_error(self, str(e))
            return
        if folder is None:
            return

        path = folder.get_path()
        get_db().set_setting("download_dir", path)
        self._dl_path_row.set_subtitle(path)
        notify(self, f"Downloads will be saved to {path}.")

    def _on_max_downloads_changed(self, row, _pspec):
        get_db().set_setting("max_simultaneous_downloads", str(int(row.get_value())))

    def _on_default_direction_changed(self, row, _pspec):
        get_db().set_setting("reading_direction", self._DIRECTION_VALUES[row.get_selected()])

    def _on_default_layout_changed(self, row, _pspec):
        get_db().set_setting("page_layout", self._LAYOUT_VALUES[row.get_selected()])

    def _on_default_background_changed(self, row, _pspec):
        get_db().set_setting("reader_background", self._BG_VALUES[row.get_selected()])

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

            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = Gtk.Label(
                label=f"{item.manga.title} – Ch.{item.chapter.chapter_number:g}"
            )
            title.set_xalign(0)
            title.set_hexpand(True)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            header.append(title)

            chapter_id = item.chapter.id
            if item.status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
                cancel_btn = Gtk.Button(label="Cancel")
                cancel_btn.add_css_class("flat")
                cancel_btn.connect("clicked", self._on_cancel_download, chapter_id)
                header.append(cancel_btn)
            elif item.status == DownloadStatus.ERROR:
                retry_btn = Gtk.Button(label="Retry")
                retry_btn.add_css_class("flat")
                retry_btn.connect("clicked", self._on_retry_download, chapter_id)
                header.append(retry_btn)
                remove_btn = Gtk.Button(label="Remove")
                remove_btn.add_css_class("flat")
                remove_btn.connect("clicked", self._on_remove_download, chapter_id)
                header.append(remove_btn)
            elif item.status == DownloadStatus.DOWNLOADED:
                remove_btn = Gtk.Button(label="Remove")
                remove_btn.add_css_class("flat")
                remove_btn.connect("clicked", self._on_remove_download, chapter_id)
                header.append(remove_btn)
            box.append(header)

            if item.status == DownloadStatus.ERROR:
                err = Gtk.Label(label=item.error_message or "Download failed")
                err.set_xalign(0)
                err.add_css_class("error")
                err.add_css_class("caption")
                box.append(err)
            elif item.status == DownloadStatus.DOWNLOADED:
                done = Gtk.Label(label="Downloaded")
                done.set_xalign(0)
                done.add_css_class("dim-label")
                done.add_css_class("caption")
                box.append(done)
            else:
                progress = Gtk.ProgressBar()
                progress.set_fraction(item.progress)
                progress.set_text(f"{item.pages_downloaded}/{item.total_pages} pages")
                progress.set_show_text(True)
                box.append(progress)

            row.set_child(box)
            self._downloads_list.append(row)

    def _on_cancel_download(self, _button, chapter_id: int):
        from ..core.downloader import get_download_manager
        get_download_manager().cancel(chapter_id)
        self._refresh_downloads()

    def _on_retry_download(self, _button, chapter_id: int):
        from ..core.downloader import get_download_manager
        get_download_manager().retry(chapter_id)
        self._refresh_downloads()

    def _on_remove_download(self, _button, chapter_id: int):
        from ..core.downloader import get_download_manager
        get_download_manager().remove(chapter_id)
        self._refresh_downloads()

    # ── Local source ──────────────────────────────────────────────────────

    def _local_source(self):
        from ..extensions.registry import get_registry
        from ..extensions.local import SOURCE_ID
        return get_registry().get(SOURCE_ID)

    def _refresh_local_dir_row(self):
        source = self._local_source()
        if source is None:
            self._local_dir_row.set_subtitle("The local source is unavailable.")
            return

        root = source.root
        if root.is_dir():
            self._local_dir_row.set_subtitle(str(root))
        else:
            self._local_dir_row.set_subtitle(f"{root} — this folder does not exist yet")

    def _on_choose_local_dir(self, button):
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose your local manga folder")
        dialog.select_folder(self, None, self._on_local_dir_chosen)

    def _on_local_dir_chosen(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
        except Exception as e:
            if "Dismissed" not in str(e):
                notify_error(self, str(e))
            return
        if folder is None:
            return

        source = self._local_source()
        if source is None:
            return

        source.set_root(folder.get_path())
        self._refresh_local_dir_row()
        notify(self, f"Local library set to {folder.get_path()}.")
        self._reload_browse_sources()

    def _on_rescan_local(self, button):
        # The source reads the folder on every call, so a rescan is just a
        # reload of whatever is showing it.
        self._reload_browse_sources()
        notify(self, "Rescanned the local library folder.")

    def _reload_browse_sources(self):
        browse = getattr(self, "_browse_view", None)
        reload_sources = getattr(browse, "reload_sources", None)
        if callable(reload_sources):
            reload_sources()

    # ── Extension repositories ────────────────────────────────────────────

    def _refresh_repo_rows(self):
        """Redraw one row per configured repository."""
        for row in self._repo_rows:
            self._repo_list_group.remove(row)
        self._repo_rows = []

        manager = get_repo_manager()
        repos = manager.get_repos()
        if not repos:
            row = Adw.ActionRow(
                title="No repositories configured",
                subtitle="Add one above to browse installable extensions.",
            )
            self._repo_list_group.add(row)
            self._repo_rows.append(row)
            return

        for url in repos:
            row = Adw.ActionRow(title=url)
            row.set_subtitle_lines(2)

            remove_btn = Gtk.Button(icon_name="user-trash-symbolic")
            remove_btn.add_css_class("flat")
            remove_btn.set_valign(Gtk.Align.CENTER)
            remove_btn.set_tooltip_text("Remove this repository")
            remove_btn.connect("clicked", self._on_remove_repo, url)
            row.add_suffix(remove_btn)

            self._repo_list_group.add(row)
            self._repo_rows.append(row)

    def _on_add_repo(self, entry):
        url = entry.get_text().strip()
        if not url:
            return
        if get_repo_manager().add_repo(url):
            entry.set_text("")
            self._refresh_repo_rows()
            notify(self, "Repository added. Refresh the Extensions tab to see it.")
            self._reload_browse_repos()
        else:
            notify_error(
                self,
                "Could not add that repository. It must be an http:// or https:// "
                "URL, and not one already configured.",
            )

    def _on_remove_repo(self, _button, url):
        if get_repo_manager().remove_repo(url):
            self._refresh_repo_rows()
            notify(self, "Repository removed.")
            self._reload_browse_repos()

    def _reload_browse_repos(self):
        """Re-fetch the available extension list after the repo set changed."""
        browse = getattr(self, "_browse_view", None)
        reload_available = getattr(browse, "reload_available", None)
        if callable(reload_available):
            reload_available()

    # ── Tracking ──────────────────────────────────────────────────────────

    def _build_tracker_row(self, service) -> Adw.ExpanderRow:
        """A collapsible row holding one service's client ID and login state."""
        row = Adw.ExpanderRow(title=service.name)

        state = Gtk.Label()
        state.add_css_class("dim-label")
        state.set_valign(Gtk.Align.CENTER)
        row.add_suffix(state)

        client_row = Adw.EntryRow(title="Client ID")
        client_row.set_text(getattr(service, "client_id", "") or "")
        client_row.connect(
            "apply", lambda entry, sv=service: self._on_tracker_client_id(sv, entry)
        )
        client_row.set_show_apply_button(True)
        row.add_row(client_row)

        login_row = Adw.ActionRow(
            title="Account",
            subtitle=(
                "Opens the service in your browser, then asks for the code it "
                "shows you."
            ),
        )
        login_btn = Gtk.Button(label="Log in")
        login_btn.add_css_class("suggested-action")
        login_btn.set_valign(Gtk.Align.CENTER)
        login_btn.connect("clicked", lambda *_b, sv=service: self._on_tracker_login(sv))
        login_row.add_suffix(login_btn)

        logout_btn = Gtk.Button(label="Log out")
        logout_btn.add_css_class("destructive-action")
        logout_btn.set_valign(Gtk.Align.CENTER)
        logout_btn.connect("clicked", lambda *_b, sv=service: self._on_tracker_logout(sv))
        login_row.add_suffix(logout_btn)
        row.add_row(login_row)

        self._tracking_rows[service.id] = {
            "row": row,
            "state": state,
            "client": client_row,
            "login": login_btn,
            "logout": logout_btn,
        }
        self._refresh_tracker_row(service)
        return row

    def _refresh_tracker_row(self, service):
        widgets = self._tracking_rows.get(service.id)
        if widgets is None:
            return

        configured = getattr(service, "is_configured", True)
        logged_in = service.is_logged_in

        if not configured:
            widgets["state"].set_text("Client ID needed")
        elif logged_in:
            widgets["state"].set_text("Logged in")
        else:
            widgets["state"].set_text("Logged out")

        widgets["login"].set_sensitive(configured and not logged_in)
        widgets["logout"].set_sensitive(logged_in)

    def _on_tracker_client_id(self, service, entry):
        from ..core.tracking.anilist import SETTING_CLIENT_ID as ANILIST_KEY
        from ..core.tracking.myanimelist import SETTING_CLIENT_ID as MAL_KEY

        key = ANILIST_KEY if service.id == "anilist" else MAL_KEY
        get_db().set_setting(key, entry.get_text().strip())
        self._refresh_tracker_row(service)
        notify(self, f"Saved the {service.name} client ID.")

    def _on_tracker_login(self, service):
        """
        Start the browser login, then ask for whatever the service showed.

        Both AniList's implicit grant and MyAnimeList's PKCE flow hand the
        user a value in the browser rather than calling back to a local
        server, so the code is pasted in here.
        """
        try:
            url = service.authorization_url()
        except Exception as exc:
            notify_error(self, str(exc))
            return

        try:
            webbrowser.open(url)
        except Exception as exc:
            notify_error(self, f"Could not open your browser: {exc}")
            return

        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True,
            heading=f"Finish {service.name} login",
            body=(
                f"{service.name} opened in your browser. Approve the request, then "
                "paste the code or the full redirect URL below."
            ),
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("Code or redirect URL")
        entry.set_margin_start(12)
        entry.set_margin_end(12)
        entry.set_margin_bottom(12)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", "Log in")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.connect(
            "response",
            lambda d, response, sv=service, e=entry: self._on_tracker_login_response(
                sv, response, e.get_text()
            ),
        )
        dialog.present()

    def _on_tracker_login_response(self, service, response, value):
        if response != "ok" or not value.strip():
            return

        def work():
            try:
                ok = service.complete_login(value)
            except Exception as exc:
                GLib.idle_add(self._on_tracker_login_done, service, False, str(exc))
                return
            GLib.idle_add(self._on_tracker_login_done, service, ok, None)

        threading.Thread(target=work, daemon=True).start()

    def _on_tracker_login_done(self, service, ok, error):
        if error is not None:
            notify_error(self, f"{service.name} login failed: {error}")
        elif not ok:
            notify_error(self, f"{service.name} login failed: no code was provided.")
        else:
            notify(self, f"Logged in to {service.name}.")
            # A successful login is the moment queued updates can go out.
            threading.Thread(
                target=lambda: get_track_manager().process_queue(), daemon=True
            ).start()

        self._refresh_tracker_row(service)
        self._refresh_tracking_queue_label()
        return False

    def _on_tracker_logout(self, service):
        service.logout()
        self._refresh_tracker_row(service)
        notify(self, f"Logged out of {service.name}.")

    def _refresh_tracking_queue_label(self):
        def work():
            try:
                pending = get_track_manager().queue.count()
            except Exception:
                pending = 0
            GLib.idle_add(
                self._tracking_queue_label.set_text,
                "None" if not pending else f"{pending} waiting",
            )

        threading.Thread(target=work, daemon=True).start()

    def _on_retry_tracking_queue(self, button):
        button.set_sensitive(False)

        def work():
            try:
                delivered = get_track_manager().process_queue()
            except Exception as exc:
                GLib.idle_add(self._on_queue_retried, button, None, str(exc))
                return
            GLib.idle_add(self._on_queue_retried, button, delivered, None)

        threading.Thread(target=work, daemon=True).start()

    def _on_queue_retried(self, button, delivered, error):
        button.set_sensitive(True)
        if error is not None:
            notify_error(self, f"Could not send pending updates: {error}")
        elif delivered:
            notify(self, f"Sent {delivered} pending tracker update(s).")
        else:
            notify(self, "No pending updates were ready to send.")
        self._refresh_tracking_queue_label()
        return False

    # ── Page cache ────────────────────────────────────────────────────────

    @staticmethod
    def _format_bytes(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    def _refresh_cache_size(self):
        def work():
            from ..core import disk_cache
            try:
                size = disk_cache.cache_size(disk_cache.KIND_PAGE)
            except Exception:
                size = 0
            GLib.idle_add(self._cache_size_label.set_text, self._format_bytes(size))

        threading.Thread(target=work, daemon=True).start()

    def _on_clear_page_cache(self, button):
        from ..core import disk_cache, image_loader

        button.set_sensitive(False)

        def work():
            try:
                freed = disk_cache.clear(disk_cache.KIND_PAGE)
            except Exception as exc:
                GLib.idle_add(self._on_cache_cleared, button, None, str(exc))
                return
            GLib.idle_add(self._on_cache_cleared, button, freed, None)

        image_loader.clear_cache()
        threading.Thread(target=work, daemon=True).start()

    def _on_cache_cleared(self, button, freed, error):
        button.set_sensitive(True)
        if error is not None:
            notify_error(self, f"Could not clear the page cache: {error}")
        else:
            notify(self, f"Freed {self._format_bytes(freed)} of cached pages.")
        self._refresh_cache_size()
        return False

    # ── Shortcuts ─────────────────────────────────────────────────────────

    #: Accelerator -> (handler name, description) for the shortcuts window.
    SHORTCUTS = (
        ("<Control>k", "_on_global_search_shortcut", "Global search"),
        ("slash", "_on_global_search_shortcut", "Global search"),
        ("<Control>r", "_on_refresh_shortcut", "Refresh the current tab"),
        ("F5", "_on_refresh_shortcut", "Refresh the current tab"),
        ("<Control>1", "_on_tab_shortcut_1", "Library"),
        ("<Control>2", "_on_tab_shortcut_2", "Updates"),
        ("<Control>3", "_on_tab_shortcut_3", "History"),
        ("<Control>4", "_on_tab_shortcut_4", "Browse"),
        ("<Control>5", "_on_tab_shortcut_5", "More"),
        ("<Control>question", "_on_shortcuts_window", "Show these shortcuts"),
        ("<Control>w", "_on_back_shortcut", "Back"),
    )

    #: Tab order, matching Ctrl+1 through Ctrl+5.
    TAB_ORDER = ("library", "updates", "history", "browse", "more")

    def _setup_shortcuts(self):
        """Install the window-wide accelerators listed in SHORTCUTS."""
        controller = Gtk.ShortcutController()
        controller.set_scope(Gtk.ShortcutScope.GLOBAL)

        for accelerator, handler_name, _description in self.SHORTCUTS:
            handler = getattr(self, handler_name)
            trigger = Gtk.ShortcutTrigger.parse_string(accelerator)
            if trigger is None:
                logger.warning("could not parse the accelerator %s", accelerator)
                continue
            controller.add_shortcut(
                Gtk.Shortcut(
                    trigger=trigger,
                    action=Gtk.CallbackAction.new(handler),
                )
            )

        self.add_controller(controller)

    def _on_global_search_shortcut(self, *_):
        self._tab_stack.set_visible_child_name("browse")
        self._browse_view.focus_global_search()
        return True

    def _on_refresh_shortcut(self, *_):
        """Reload whichever tab is showing."""
        current = self._tab_stack.get_visible_child_name()
        if current == "library":
            self._library_view.reload()
        elif current == "updates":
            self._updates_view.refresh_cached()
        elif current == "history":
            refresh = getattr(self._history_view, "reload", None)
            if callable(refresh):
                refresh()
        elif current == "browse":
            self._browse_view.reload_sources()
        return True

    def _switch_to_tab(self, index: int) -> bool:
        if 0 <= index < len(self.TAB_ORDER):
            self._tab_stack.set_visible_child_name(self.TAB_ORDER[index])
        return True

    # One handler per accelerator: Gtk.CallbackAction passes no user data, so
    # the index cannot be bound through the shortcut itself.
    def _on_tab_shortcut_1(self, *_):
        return self._switch_to_tab(0)

    def _on_tab_shortcut_2(self, *_):
        return self._switch_to_tab(1)

    def _on_tab_shortcut_3(self, *_):
        return self._switch_to_tab(2)

    def _on_tab_shortcut_4(self, *_):
        return self._switch_to_tab(3)

    def _on_tab_shortcut_5(self, *_):
        return self._switch_to_tab(4)

    def _on_back_shortcut(self, *_):
        """Pop one page off the navigation stack, if there is one."""
        try:
            self._nav_view.pop()
        except Exception:
            pass
        return True

    def _on_shortcuts_window(self, *_):
        self._show_shortcuts_window()
        return True

    def _show_shortcuts_window(self):
        """
        Build the standard GTK shortcuts overlay from SHORTCUTS.

        Accelerators that share a handler (Ctrl+K and /) are listed once with
        both keys, which is how the overlay expects alternatives.
        """
        window = Gtk.ShortcutsWindow(transient_for=self, modal=True)
        section = Gtk.ShortcutsSection(section_name="main", max_height=12)

        grouped = {}
        order = []
        for accelerator, handler_name, description in self.SHORTCUTS:
            if description not in grouped:
                grouped[description] = []
                order.append(description)
            grouped[description].append(accelerator)

        group = Gtk.ShortcutsGroup(title="Mihon")
        for description in order:
            group.add_shortcut(Gtk.ShortcutsShortcut(
                title=description,
                accelerator=" ".join(grouped[description]),
            ))
        section.add_group(group)

        reader_group = Gtk.ShortcutsGroup(title="Reader")
        for title, accelerator in (
            ("Next page", "Right space"),
            ("Previous page", "Left BackSpace"),
            ("Close the reader", "Escape"),
        ):
            reader_group.add_shortcut(
                Gtk.ShortcutsShortcut(title=title, accelerator=accelerator)
            )
        section.add_group(reader_group)

        window.add_section(section)
        window.present()

    # ── Backup / restore ──────────────────────────────────────────────────

    @staticmethod
    def _tachibk_filters():
        """A filter model matching .tachibk plus an all-files escape hatch."""
        tachibk = Gtk.FileFilter()
        tachibk.set_name("Mihon Android backup")
        tachibk.add_pattern("*.tachibk")

        any_file = Gtk.FileFilter()
        any_file.set_name("All files")
        any_file.add_pattern("*")

        model = Gio.ListStore(item_type=Gtk.FileFilter)
        model.append(tachibk)
        model.append(any_file)
        return model, tachibk

    def _show_message(self, heading: str, body: str):
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True,
            heading=heading,
            body=body,
        )
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present()

    def _busy_dialog(self, heading: str, body: str):
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True,
            heading=heading,
            body=body,
        )
        dialog.present()
        return dialog

    def _on_import_tachibk_clicked(self, button):
        dialog = Gtk.FileDialog()
        dialog.set_title("Select .tachibk backup file")
        filters, default_filter = self._tachibk_filters()
        dialog.set_filters(filters)
        dialog.set_default_filter(default_filter)
        dialog.open(self, None, self._on_import_file_chosen)

    def _on_import_file_chosen(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except Exception as e:
            # The user dismissing the chooser is not an error worth reporting.
            if "Dismissed" not in str(e):
                self._show_message("Import failed", str(e))
            return
        if file is None:
            return

        path = Path(file.get_path())
        busy = self._busy_dialog(
            "Importing backup",
            f"Reading {path.name}. This can take a while for a large library.",
        )

        def work():
            from ..core.tachibk_importer import import_tachibk
            try:
                result = import_tachibk(path, apply=True)
            except Exception as exc:
                GLib.idle_add(self._on_import_done, busy, None, str(exc))
                return
            GLib.idle_add(self._on_import_done, busy, result, None)

        threading.Thread(target=work, daemon=True).start()

    def _on_import_done(self, busy, result, error):
        busy.close()
        if error is not None:
            self._show_message("Import failed", error)
            return False
        if result is None or not result.ok:
            errors = "\n".join(result.errors) if result else "Unknown error"
            self._show_message("Import failed", errors)
            return False

        self._show_message("Import complete", result.summary())
        notify(self, result.summary())
        self._refresh_after_import()
        return False

    def _refresh_after_import(self):
        """Pull the newly imported rows into the views that are already built."""
        try:
            self._library_view.reload()
        except Exception as exc:
            logger.error("library reload after import failed: %s", exc)
        try:
            self._updates_view.refresh_cached()
        except Exception as exc:
            logger.error("updates refresh after import failed: %s", exc)

    def _on_export_tachibk_clicked(self, button):
        from ..core.tachibk_exporter import default_backup_name

        dialog = Gtk.FileDialog()
        dialog.set_title("Save .tachibk backup")
        dialog.set_initial_name(default_backup_name())
        filters, default_filter = self._tachibk_filters()
        dialog.set_filters(filters)
        dialog.set_default_filter(default_filter)
        dialog.save(self, None, self._on_export_file_chosen)

    def _on_export_file_chosen(self, dialog, result):
        try:
            file = dialog.save_finish(result)
        except Exception as e:
            if "Dismissed" not in str(e):
                self._show_message("Export failed", str(e))
            return
        if file is None:
            return

        path = Path(file.get_path())
        busy = self._busy_dialog(
            "Exporting backup",
            f"Writing {path.name}.",
        )

        def work():
            from ..core.tachibk_exporter import export_tachibk
            try:
                result = export_tachibk(path)
            except Exception as exc:
                GLib.idle_add(self._on_export_done, busy, None, str(exc))
                return
            GLib.idle_add(self._on_export_done, busy, result, None)

        threading.Thread(target=work, daemon=True).start()

    def _on_export_done(self, busy, result, error):
        busy.close()
        if error is not None:
            self._show_message("Export failed", error)
            return False
        if result is None or not result.ok:
            self._show_message("Export failed", result.summary() if result else "Unknown error")
            return False
        self._show_message("Export complete", f"{result.summary()}\n\nSaved to {result.path}")
        return False
