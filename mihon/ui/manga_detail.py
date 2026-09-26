"""
Manga detail view - shows manga info, chapter list, add to library.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio, GdkPixbuf, Pango
import threading
import time
import os
import shutil
import webbrowser
from urllib.parse import urljoin
from ..core.database import get_db
from ..core.models import Manga, Chapter, ReadingStatus, DownloadStatus, SearchFilter
from ..core import disk_cache, image_loader
from ..core.tracking import (
    ALL_STATUSES,
    STATUS_LABELS,
    TrackEntry,
    get_track_manager,
)
from ..extensions.registry import get_registry
from ..core.downloader import get_download_manager
from .notify import notify, notify_error
import logging

logger = logging.getLogger("manga_detail")



class MangaDetailView(Gtk.Box):
    """
    Full detail page for a manga:
    - Cover, title, author, genres
    - Add to library / reading status
    - Chapter list with read/download controls
    """

    def __init__(self, on_read_chapter=None, on_back=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_read_chapter = on_read_chapter
        self._on_back = on_back
        self._manga: Manga = None
        self._chapters = []
        self._chapter_filter_mode = "all"  # all | unread | read | downloaded
        self._chapter_query = ""
        self._chapter_selection_mode = False
        self._selected_chapter_ids = set()
        self._tracking_cache = {}
        self._db = get_db()

        self._build_ui()

    def _build_ui(self):
        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        # show_start_title_buttons is True by default for NavigationView to display the back button

        self.append(header)

        # Main scrollable content
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # ── Header Overlay (Parallax/Blurred Background) ───────────────────
        header_overlay = Gtk.Overlay()
        header_overlay.set_hexpand(True)

        self._bg_cover = Gtk.Picture()
        self._bg_cover.set_content_fit(Gtk.ContentFit.COVER)
        self._bg_cover.set_opacity(0.15)
        self._bg_cover.set_can_focus(False)
        self._bg_cover.set_hexpand(True)
        self._bg_cover.add_css_class("view")
        header_overlay.set_child(self._bg_cover)

        # ── Info section (Foreground of Overlay) ───────────────────────────
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        info_box.set_valign(Gtk.Align.END)
        info_box.set_margin_start(24)
        info_box.set_margin_end(24)
        info_box.set_margin_top(48)
        info_box.set_margin_bottom(24)

        # Cover (Front)
        cover_frame = Gtk.Frame()
        cover_frame.add_css_class("card")
        self._cover = Gtk.Picture()
        self._cover.set_content_fit(Gtk.ContentFit.COVER)
        self._cover.set_size_request(120, 180)
        cover_frame.set_child(self._cover)
        info_box.append(cover_frame)

        # Text info
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_vexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        self._manga_title = Gtk.Label()
        self._manga_title.set_wrap(True)
        self._manga_title.set_xalign(0)
        self._manga_title.add_css_class("title-1")
        text_box.append(self._manga_title)

        self._author_label = Gtk.Label()
        self._author_label.set_xalign(0)
        self._author_label.add_css_class("dim-label")
        text_box.append(self._author_label)

        self._status_label = Gtk.Label()
        self._status_label.set_xalign(0)
        text_box.append(self._status_label)

        # Genre chips
        self._genre_box = Gtk.FlowBox()
        self._genre_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._genre_box.set_column_spacing(4)
        self._genre_box.set_row_spacing(4)
        text_box.append(self._genre_box)

        # Score
        self._score_label = Gtk.Label()
        self._score_label.set_xalign(0)
        self._score_label.add_css_class("dim-label")
        text_box.append(self._score_label)

        info_box.append(text_box)
        header_overlay.add_overlay(info_box)
        header_overlay.set_measure_overlay(info_box, True)

        main_box.append(header_overlay)

        # ── Action buttons ─────────────────────────────────────────────────
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        action_box.set_margin_start(16)
        action_box.set_margin_end(16)
        action_box.set_margin_top(8)
        action_box.set_margin_bottom(16)

        # Add to Library / Tracking
        lib_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._library_btn = Gtk.Button(icon_name="bookmark-new-symbolic")
        self._library_btn.add_css_class("circular")
        self._library_btn.set_size_request(48, 48)
        self._library_btn.set_halign(Gtk.Align.CENTER)
        self._library_btn.connect("clicked", self._toggle_library)
        lib_box.append(self._library_btn)
        lib_lbl = Gtk.Label(label="Add")
        lib_lbl.add_css_class("caption")
        lib_box.append(lib_lbl)
        action_box.append(lib_box)

        # Reading status
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        status_btn = Gtk.MenuButton(icon_name="object-select-symbolic")
        status_btn.add_css_class("circular")
        status_btn.set_size_request(48, 48)
        status_btn.set_halign(Gtk.Align.CENTER)
        status_btn.set_tooltip_text("Reading status")
        status_btn.set_popover(self._build_reading_status_menu())
        status_box.append(status_btn)
        status_lbl = Gtk.Label(label="Status")
        status_lbl.add_css_class("caption")
        status_box.append(status_lbl)
        action_box.append(status_box)

        # WebView / Browse
        web_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        web_btn = Gtk.Button(icon_name="web-browser-symbolic")
        web_btn.add_css_class("circular")
        web_btn.set_size_request(48, 48)
        web_btn.set_halign(Gtk.Align.CENTER)
        web_btn.connect("clicked", self._open_web_view)
        self._web_btn = web_btn
        web_box.append(web_btn)
        web_lbl = Gtk.Label(label="WebView")
        web_lbl.add_css_class("caption")
        web_box.append(web_lbl)
        action_box.append(web_box)

        # Tracking
        track_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        track_btn = Gtk.Button(icon_name="network-transmit-receive-symbolic")
        track_btn.add_css_class("circular")
        track_btn.set_size_request(48, 48)
        track_btn.set_halign(Gtk.Align.CENTER)
        track_btn.set_tooltip_text("Manage tracking")
        track_btn.connect("clicked", self._open_tracking_dialog)
        track_box.append(track_btn)
        track_lbl = Gtk.Label(label="Track")
        track_lbl.add_css_class("caption")
        track_box.append(track_lbl)
        action_box.append(track_box)

        # Migrate
        migrate_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        migrate_btn = Gtk.Button(icon_name="system-search-symbolic")
        migrate_btn.add_css_class("circular")
        migrate_btn.set_size_request(48, 48)
        migrate_btn.set_halign(Gtk.Align.CENTER)
        migrate_btn.set_tooltip_text("Find migration target")
        migrate_btn.connect("clicked", self._open_migration_dialog)
        migrate_box.append(migrate_btn)
        migrate_lbl = Gtk.Label(label="Migrate")
        migrate_lbl.add_css_class("caption")
        migrate_box.append(migrate_lbl)
        action_box.append(migrate_box)

        # Continue reading button (Dominant FAB)
        self._continue_btn = Gtk.Button(label="Continue")
        self._continue_btn.add_css_class("suggested-action")
        self._continue_btn.add_css_class("pill")
        self._continue_btn.set_hexpand(True)
        self._continue_btn.set_valign(Gtk.Align.CENTER)
        self._continue_btn.set_size_request(-1, 48)
        self._continue_btn.connect("clicked", self._continue_reading)
        action_box.append(self._continue_btn)

        main_box.append(action_box)

        self._tracking_summary = Gtk.Label(label="Tracking: none")
        self._tracking_summary.set_xalign(0)
        self._tracking_summary.add_css_class("dim-label")
        self._tracking_summary.set_margin_start(16)
        self._tracking_summary.set_margin_end(16)
        self._tracking_summary.set_margin_bottom(10)
        main_box.append(self._tracking_summary)

        # ── Description ────────────────────────────────────────────────────
        desc_expander = Gtk.Expander(label="Description")
        desc_expander.set_margin_start(16)
        desc_expander.set_margin_end(16)
        desc_expander.set_margin_bottom(8)
        self._description = Gtk.Label()
        self._description.set_wrap(True)
        self._description.set_xalign(0)
        self._description.set_selectable(True)
        desc_expander.set_child(self._description)
        main_box.append(desc_expander)

        # ── Chapter list header ────────────────────────────────────────────
        ch_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ch_header.set_margin_start(16)
        ch_header.set_margin_end(16)
        ch_header.set_margin_top(4)
        ch_header.set_margin_bottom(4)

        self._chapter_count_label = Gtk.Label()
        self._chapter_count_label.add_css_class("heading")
        self._chapter_count_label.set_hexpand(True)
        self._chapter_count_label.set_xalign(0)
        ch_header.append(self._chapter_count_label)

        # Sort toggle
        sort_btn = Gtk.ToggleButton(icon_name="view-sort-descending-symbolic")
        sort_btn.set_tooltip_text("Reverse chapter order")
        sort_btn.set_active(True)
        sort_btn.connect("toggled", self._toggle_sort)
        self._sort_descending = True
        ch_header.append(sort_btn)

        # Chapter number is meaningless on sources that do not number their
        # chapters, so the source's own ordering is offered as an alternative.
        self._chapter_sort = "number"
        sort_mode_btn = Gtk.MenuButton(icon_name="view-list-ordered-symbolic")
        sort_mode_btn.set_tooltip_text("Chapter sort order")
        sort_mode_pop = Gtk.Popover()
        sort_mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sort_mode_box.set_margin_start(8)
        sort_mode_box.set_margin_end(8)
        sort_mode_box.set_margin_top(8)
        sort_mode_box.set_margin_bottom(8)

        self._chapter_sort_buttons = {}
        first_btn = None
        for key, label in (
            ("number", "Chapter number"),
            ("source", "Source order"),
            ("upload", "Upload date"),
        ):
            btn = Gtk.CheckButton(label=label)
            if first_btn is None:
                first_btn = btn
                btn.set_active(True)
            else:
                btn.set_group(first_btn)
            btn.connect("toggled", self._set_chapter_sort, key)
            sort_mode_box.append(btn)
            self._chapter_sort_buttons[key] = btn

        sort_mode_pop.set_child(sort_mode_box)
        sort_mode_btn.set_popover(sort_mode_pop)
        ch_header.append(sort_mode_btn)

        # Mark all read
        mark_all_btn = Gtk.Button(icon_name="emblem-ok-symbolic")
        mark_all_btn.set_tooltip_text("Mark all as read")
        mark_all_btn.connect("clicked", self._mark_all_read)
        ch_header.append(mark_all_btn)

        # Download Menu
        dl_menu_btn = Gtk.MenuButton(icon_name="folder-download-symbolic")
        dl_menu_btn.set_tooltip_text("Download Chapters")
        
        dl_pop = Gtk.Popover()
        dl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        dl_box.set_margin_start(4)
        dl_box.set_margin_end(4)
        dl_box.set_margin_top(4)
        dl_box.set_margin_bottom(4)
        
        dl_unread_btn = Gtk.Button(label="Download Unread")
        dl_unread_btn.add_css_class("flat")
        dl_unread_btn.connect("clicked", lambda *_: (self._download_unread(), dl_pop.popdown()))
        dl_box.append(dl_unread_btn)
        
        dl_all_btn = Gtk.Button(label="Download All")
        dl_all_btn.add_css_class("flat")
        dl_all_btn.connect("clicked", lambda *_: (self._download_all_chapters(), dl_pop.popdown()))
        dl_box.append(dl_all_btn)
        
        dl_pop.set_child(dl_box)
        dl_menu_btn.set_popover(dl_pop)
        ch_header.append(dl_menu_btn)

        main_box.append(ch_header)

        # Chapter filter/search tools
        ch_tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ch_tools.set_margin_start(16)
        ch_tools.set_margin_end(16)
        ch_tools.set_margin_bottom(6)

        self._chapter_search = Gtk.SearchEntry()
        self._chapter_search.set_placeholder_text("Filter chapters...")
        self._chapter_search.set_hexpand(True)
        self._chapter_search.connect("search-changed", self._on_chapter_search_changed)
        ch_tools.append(self._chapter_search)

        filter_menu_btn = Gtk.MenuButton(icon_name="funnel-symbolic")
        filter_menu_btn.set_tooltip_text("Chapter filters")
        filter_menu_btn.set_popover(self._build_chapter_filter_menu())
        ch_tools.append(filter_menu_btn)

        batch_menu_btn = Gtk.MenuButton(icon_name="edit-select-all-symbolic")
        batch_menu_btn.set_tooltip_text("Batch chapter actions (filtered)")
        batch_menu_btn.set_popover(self._build_chapter_batch_menu())
        ch_tools.append(batch_menu_btn)

        self._select_toggle_btn = Gtk.ToggleButton(icon_name="object-select-symbolic")
        self._select_toggle_btn.set_tooltip_text("Select chapters")
        self._select_toggle_btn.connect("toggled", self._on_select_toggle)
        ch_tools.append(self._select_toggle_btn)

        main_box.append(ch_tools)

        # ── Selection action bar (shown only while selecting chapters) ─────
        self._selection_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._selection_bar.set_margin_start(16)
        self._selection_bar.set_margin_end(16)
        self._selection_bar.set_margin_bottom(6)
        self._selection_bar.set_visible(False)

        self._selection_count_label = Gtk.Label(label="0 selected")
        self._selection_count_label.set_hexpand(True)
        self._selection_count_label.set_xalign(0)
        self._selection_count_label.add_css_class("dim-label")
        self._selection_bar.append(self._selection_count_label)

        sel_all_btn = Gtk.Button(label="All")
        sel_all_btn.add_css_class("flat")
        sel_all_btn.connect("clicked", self._on_select_all_clicked)
        self._selection_bar.append(sel_all_btn)

        sel_none_btn = Gtk.Button(label="None")
        sel_none_btn.add_css_class("flat")
        sel_none_btn.connect("clicked", self._on_select_none_clicked)
        self._selection_bar.append(sel_none_btn)

        sel_read_btn = Gtk.Button(label="Mark Read")
        sel_read_btn.add_css_class("flat")
        sel_read_btn.connect("clicked", self._on_selection_mark_read)
        self._selection_bar.append(sel_read_btn)

        sel_unread_btn = Gtk.Button(label="Mark Unread")
        sel_unread_btn.add_css_class("flat")
        sel_unread_btn.connect("clicked", self._on_selection_mark_unread)
        self._selection_bar.append(sel_unread_btn)

        sel_dl_btn = Gtk.Button(label="Download")
        sel_dl_btn.add_css_class("flat")
        sel_dl_btn.connect("clicked", self._on_selection_download)
        self._selection_bar.append(sel_dl_btn)

        sel_del_btn = Gtk.Button(label="Delete")
        sel_del_btn.add_css_class("flat")
        sel_del_btn.add_css_class("error")
        sel_del_btn.connect("clicked", self._on_selection_clear_downloads)
        self._selection_bar.append(sel_del_btn)

        main_box.append(self._selection_bar)
        main_box.append(Gtk.Separator())

        # ── Chapter list ───────────────────────────────────────────────────
        self._chapter_list = Gtk.ListBox()
        self._chapter_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._chapter_list.add_css_class("boxed-list")
        self._chapter_list.set_margin_start(16)
        self._chapter_list.set_margin_end(16)
        self._chapter_list.set_margin_top(8)
        self._chapter_list.set_margin_bottom(16)

        main_box.append(self._chapter_list)

        scroll.set_child(main_box)
        self.append(scroll)

    def _build_chapter_filter_menu(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        first = None
        self._chapter_filter_buttons = {}
        for mode, label in [
            ("all", "All Chapters"),
            ("unread", "Unread"),
            ("read", "Read"),
            ("downloaded", "Downloaded"),
        ]:
            btn = Gtk.CheckButton(label=label)
            if first is None:
                first = btn
            else:
                btn.set_group(first)
            btn.set_active(mode == "all")
            btn.connect("toggled", self._on_chapter_filter_mode_changed, mode, pop)
            self._chapter_filter_buttons[mode] = btn
            box.append(btn)

        pop.set_child(box)
        return pop

    def _build_chapter_batch_menu(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        mark_read_btn = Gtk.Button(label="Mark Filtered Read")
        mark_read_btn.add_css_class("flat")
        mark_read_btn.connect("clicked", lambda *_: self._batch_mark_filtered_read(pop))
        box.append(mark_read_btn)

        mark_unread_btn = Gtk.Button(label="Mark Filtered Unread")
        mark_unread_btn.add_css_class("flat")
        mark_unread_btn.connect("clicked", lambda *_: self._batch_mark_filtered_unread(pop))
        box.append(mark_unread_btn)

        dl_btn = Gtk.Button(label="Download Filtered")
        dl_btn.add_css_class("flat")
        dl_btn.connect("clicked", lambda *_: self._batch_download_filtered(pop))
        box.append(dl_btn)

        clear_dl_btn = Gtk.Button(label="Clear Filtered Downloads")
        clear_dl_btn.add_css_class("flat")
        clear_dl_btn.add_css_class("error")
        clear_dl_btn.connect("clicked", lambda *_: self._batch_clear_filtered_downloads(pop))
        box.append(clear_dl_btn)

        pop.set_child(box)
        return pop

    def _build_reading_status_menu(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(4)
        box.set_margin_end(4)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        for status in [
            ReadingStatus.READING,
            ReadingStatus.COMPLETED,
            ReadingStatus.ON_HOLD,
            ReadingStatus.DROPPED,
            ReadingStatus.PLAN_TO_READ,
        ]:
            btn = Gtk.Button(label=status.value.replace("_", " ").title())
            btn.add_css_class("flat")
            btn.connect("clicked", self._set_reading_status, status, pop)
            box.append(btn)

        clear_btn = Gtk.Button(label="Clear Status")
        clear_btn.add_css_class("flat")
        clear_btn.connect("clicked", self._set_reading_status, ReadingStatus.NONE, pop)
        box.append(clear_btn)

        pop.set_child(box)
        return pop

    def load_manga(self, manga: Manga):
        """Load and display a manga's details."""
        self._manga = manga
        self._update_web_button_state()
        self._chapter_query = ""
        self._chapter_filter_mode = "all"
        self._chapter_search.set_text("")
        for mode, btn in getattr(self, "_chapter_filter_buttons", {}).items():
            btn.set_active(mode == "all")
        self._selected_chapter_ids = set()
        self._set_chapter_selection_mode(False)
        self._manga_title.set_text(manga.title)
        self._author_label.set_text(manga.author or "Unknown Author")
        self._status_label.set_markup(
            f"<b>Status:</b> {manga.status.title() if manga.status else 'Unknown'}"
        )
        self._description.set_text(manga.description or "No description available.")
        if manga.score:
            self._score_label.set_text(f"⭐ {manga.score:.1f}/10")
        else:
            self._score_label.set_text("")

        # Genres
        child = self._genre_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._genre_box.remove(child)
            child = nxt
        for genre in manga.genres[:10]:
            chip = Gtk.Label(label=genre)
            chip.add_css_class("tag")
            chip.add_css_class("caption")
            chip.set_margin_start(4)
            chip.set_margin_end(4)
            chip.set_margin_top(2)
            chip.set_margin_bottom(2)
            self._genre_box.append(chip)

        self._update_library_button()
        self._refresh_tracking_summary()

        # Load cover. cover_local_path is a filesystem path, not a URL - if it
        # exists, read it directly rather than handing it to load_image_async,
        # which would treat it as a URL and fail (a disk cache path has no
        # scheme/host for curl to reject it on).
        if manga.cover_local_path and GLib.file_test(manga.cover_local_path, GLib.FileTest.EXISTS):
            pixbuf = image_loader.load_local_image(manga.cover_local_path, width=320, height=480)
            if pixbuf:
                self._on_cover_loaded(pixbuf)
        elif manga.cover_url:
            image_loader.load_image_async(
                manga.cover_url,
                self._on_cover_loaded,
                width=320, height=480,  # Higher resolution for the blurred background
                kind=disk_cache.KIND_COVER,
            )
            # Record where the cover landed so the library grid can read it
            # straight off disk instead of going back to the network.
            self._remember_cover_path(manga, manga.cover_url)

        # Load details + chapters in background
        self._load_details()

    def _remember_cover_path(self, manga, url: str):
        """Persist the on-disk cover path once the file exists."""
        if manga is None or manga.id is None or manga.cover_local_path:
            return

        def check():
            path = image_loader.cached_path(url, disk_cache.KIND_COVER)
            if path is None:
                return True  # Not fetched yet; look again on the next tick.
            try:
                get_db().update_cover_path(manga.id, path)
                manga.cover_local_path = path
            except Exception as exc:
                logger.warning("could not record cover path: %s", exc)
            return False

        GLib.timeout_add(500, check)

    def _on_cover_loaded(self, pixbuf):
        if not pixbuf:
            return
        
        # Set foreground cover
        self._cover.set_pixbuf(pixbuf)
        
        # Set background cover (it will be scaled by the widget because of COVER fit)
        self._bg_cover.set_pixbuf(pixbuf)

    def _load_details(self):
        manga = self._manga
        ext = get_registry().get(manga.source_id)
        if not ext:
            return

        def fetch():
            try:
                # A manga already initialized carries everything the details
                # call would return, so skip the round trip and go straight to
                # chapters. This is Android's SManga.initialized behaviour.
                if manga.initialized and manga.id:
                    updated = manga
                else:
                    updated = ext.get_manga_details(manga)
                    updated.initialized = True
                updated.in_library = manga.in_library
                updated.reading_status = manga.reading_status
                updated.added_at = manga.added_at
                if manga.cover_local_path:
                    updated.cover_local_path = manga.cover_local_path
                # Update DB
                db_id = self._db.upsert_manga(updated)
                updated.id = db_id

                # Chapters are always re-fetched: unlike details, the list
                # grows as the series updates.
                chapters = ext.get_chapters(updated)
                logger.debug("extension returned %d chapters", len(chapters))
                for ch in chapters:
                    ch.manga_id = db_id
                self._db.upsert_chapters(chapters)
                # Re-fetch from DB to get IDs
                db_chapters = self._db.get_chapters(db_id, sort=self._chapter_sort)
                logger.debug("db returned %d chapters after upsert", len(db_chapters))
                GLib.idle_add(self._on_details_loaded, updated, db_chapters)
            except Exception as e:
                logger.error("error loading details: %s", e)
                # Still try to show cached chapters
                if manga.id:
                    db_chapters = self._db.get_chapters(manga.id)
                    GLib.idle_add(self._on_details_loaded, manga, db_chapters)

        threading.Thread(target=fetch, daemon=True).start()

    def _on_details_loaded(self, manga: Manga, chapters):
        self._manga = manga
        self._update_web_button_state()
        self._chapters = chapters
        self._render_chapters()
        self._update_library_button()
        self._refresh_tracking_summary()

    def _resolve_external_manga_url(self):
        if not self._manga:
            return None

        raw_url = (self._manga.url or self._manga.source_manga_id or "").strip()
        if not raw_url:
            return None

        if raw_url.startswith(("https://", "http://")):
            return raw_url
        if raw_url.startswith("//"):
            return f"https:{raw_url}"

        # Many JVM extensions return relative manga URLs; normalize against source base URL.
        ext = get_registry().get(self._manga.source_id)
        base_url = getattr(ext, "_base_url", "") if ext else ""
        if base_url:
            return urljoin(base_url.rstrip("/") + "/", raw_url.lstrip("/"))

        return None

    def _update_web_button_state(self):
        if not hasattr(self, "_web_btn"):
            return
        url = self._resolve_external_manga_url()
        if url:
            self._web_btn.set_sensitive(True)
            self._web_btn.set_tooltip_text(url)
        else:
            self._web_btn.set_sensitive(False)
            self._web_btn.set_tooltip_text("No website URL available for this source")

    def _open_web_view(self, *_):
        url = self._resolve_external_manga_url()
        if not url:
            self._update_web_button_state()
            return
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except Exception as e:
            print(f"[detail] Failed to open browser URL '{url}': {e}")

    def _render_chapters(self):
        # Clear
        child = self._chapter_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._chapter_list.remove(child)
            child = nxt

        chapters = self._sort_chapters(self._get_filtered_chapters())

        total = len(self._chapters)
        shown = len(chapters)
        if shown == total:
            self._chapter_count_label.set_text(f"{total} Chapters")
        else:
            self._chapter_count_label.set_text(f"{total} Chapters ({shown} shown)")

        for chapter in chapters:
            row = self._make_chapter_row(chapter)
            self._chapter_list.append(row)

    def _get_filtered_chapters(self):
        chapters = list(self._chapters)
        mode = self._chapter_filter_mode
        if mode == "unread":
            chapters = [c for c in chapters if not c.read]
        elif mode == "read":
            chapters = [c for c in chapters if c.read]
        elif mode == "downloaded":
            chapters = [c for c in chapters if c.download_status == DownloadStatus.DOWNLOADED]

        query = (self._chapter_query or "").strip().lower()
        if query:
            def match(ch: Chapter):
                chapter_label = f"chapter {ch.chapter_number:g}" if ch.chapter_number >= 0 else ""
                return (
                    query in (ch.title or "").lower()
                    or query in chapter_label
                )
            chapters = [c for c in chapters if match(c)]
        return chapters

    def _on_chapter_search_changed(self, entry):
        self._chapter_query = entry.get_text().strip().lower()
        self._render_chapters()

    def _on_chapter_filter_mode_changed(self, btn, mode: str, popover):
        if not btn.get_active():
            return
        self._chapter_filter_mode = mode
        popover.popdown()
        self._render_chapters()

    def _batch_mark_filtered_read(self, popover):
        popover.popdown()
        self._batch_mark_read(self._get_filtered_chapters())

    def _batch_mark_filtered_unread(self, popover):
        popover.popdown()
        self._batch_mark_unread(self._get_filtered_chapters())

    def _batch_download_filtered(self, popover):
        popover.popdown()
        self._batch_download(self._get_filtered_chapters())

    def _batch_clear_filtered_downloads(self, popover):
        popover.popdown()
        self._batch_clear_downloads(self._get_filtered_chapters())

    # ── Shared batch primitives (used by both the filtered-batch menu and
    # ── the checkbox multi-select bar) ──────────────────────────────────

    def _batch_mark_read(self, chapters):
        for ch in chapters:
            if not ch.read and ch.id:
                self._db.mark_chapter_read(ch.id)
                ch.read = True
        self._render_chapters()

    def _batch_mark_unread(self, chapters):
        for ch in chapters:
            if ch.read and ch.id:
                self._db.mark_chapter_unread(ch.id)
                ch.read = False
        self._render_chapters()

    def _batch_download(self, chapters):
        for ch in chapters:
            if ch.download_status != DownloadStatus.DOWNLOADED:
                self._download_chapter(ch)

    def _batch_clear_downloads(self, chapters):
        for ch in chapters:
            if ch.download_status != DownloadStatus.DOWNLOADED:
                continue
            if ch.local_path and os.path.exists(ch.local_path):
                try:
                    if os.path.isdir(ch.local_path):
                        shutil.rmtree(ch.local_path)
                    else:
                        os.remove(ch.local_path)
                except Exception:
                    pass
            if ch.id:
                self._db.clear_chapter_download(ch.id)
            ch.download_status = DownloadStatus.NOT_DOWNLOADED
            ch.local_path = None
        self._render_chapters()

    # ── Checkbox multi-select ────────────────────────────────────────────

    def _on_select_toggle(self, btn):
        self._set_chapter_selection_mode(btn.get_active())

    def _set_chapter_selection_mode(self, enabled: bool):
        self._chapter_selection_mode = enabled
        if hasattr(self, "_select_toggle_btn"):
            self._select_toggle_btn.set_active(enabled)
        if not enabled:
            self._selected_chapter_ids = set()
        if hasattr(self, "_selection_bar"):
            self._selection_bar.set_visible(enabled)
        self._update_selection_count()
        self._render_chapters()

    def _update_selection_count(self):
        if hasattr(self, "_selection_count_label"):
            self._selection_count_label.set_text(f"{len(self._selected_chapter_ids)} selected")

    def _on_chapter_checkbox_toggled(self, btn, chapter_id):
        if btn.get_active():
            self._selected_chapter_ids.add(chapter_id)
        else:
            self._selected_chapter_ids.discard(chapter_id)
        self._update_selection_count()

    def _on_select_all_clicked(self, *_):
        self._selected_chapter_ids = {ch.id for ch in self._get_filtered_chapters() if ch.id}
        self._update_selection_count()
        self._render_chapters()

    def _on_select_none_clicked(self, *_):
        self._selected_chapter_ids = set()
        self._update_selection_count()
        self._render_chapters()

    def _selected_chapters(self):
        return [ch for ch in self._chapters if ch.id in self._selected_chapter_ids]

    def _on_selection_mark_read(self, *_):
        self._batch_mark_read(self._selected_chapters())

    def _on_selection_mark_unread(self, *_):
        self._batch_mark_unread(self._selected_chapters())

    def _on_selection_download(self, *_):
        self._batch_download(self._selected_chapters())

    def _on_selection_clear_downloads(self, *_):
        self._batch_clear_downloads(self._selected_chapters())

    def _make_chapter_row(self, chapter: Chapter) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_activatable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        if self._chapter_selection_mode and chapter.id:
            check = Gtk.CheckButton()
            check.set_active(chapter.id in self._selected_chapter_ids)
            check.set_valign(Gtk.Align.CENTER)
            check.connect("toggled", self._on_chapter_checkbox_toggled, chapter.id)
            box.append(check)

        # Chapter info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)

        if chapter.chapter_number >= 0:
            ch_label = Gtk.Label(label=f"Chapter {chapter.chapter_number:g}")
        else:
            ch_label = Gtk.Label(label=chapter.title or "Unknown")
        ch_label.set_xalign(0)
        if chapter.read:
            ch_label.add_css_class("dim-label")
        else:
            ch_label.add_css_class("body")
        info_box.append(ch_label)

        if chapter.title and chapter.title != f"Chapter {chapter.chapter_number:g}":
            sub = Gtk.Label(label=chapter.title)
            sub.set_xalign(0)
            sub.add_css_class("caption")
            sub.add_css_class("dim-label")
            info_box.append(sub)

        # Date
        if chapter.uploaded_at:
            from datetime import datetime
            dt = datetime.fromtimestamp(chapter.uploaded_at)
            date_str = dt.strftime("%b %d, %Y")
            date_lbl = Gtk.Label(label=date_str)
            date_lbl.set_xalign(0)
            date_lbl.add_css_class("caption")
            date_lbl.add_css_class("dim-label")
            info_box.append(date_lbl)

        box.append(info_box)

        # Download indicator
        if chapter.download_status == DownloadStatus.DOWNLOADED:
            dl_icon = Gtk.Image.new_from_icon_name("folder-download-symbolic")
            dl_icon.add_css_class("success")
            box.append(dl_icon)

        # Read button
        read_btn = Gtk.Button(icon_name="media-playback-start-symbolic")
        read_btn.set_tooltip_text("Read chapter")
        read_btn.add_css_class("flat")
        read_btn.connect("clicked", self._on_read_clicked, chapter)
        box.append(read_btn)

        # Menu button (download, mark read, etc.)
        menu_btn = Gtk.MenuButton(icon_name="view-more-symbolic")
        menu_btn.add_css_class("flat")
        menu_btn.set_popover(self._make_chapter_menu(chapter))
        box.append(menu_btn)

        row.set_child(box)
        return row

    def _make_chapter_menu(self, chapter: Chapter) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(4)
        box.set_margin_end(4)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        # Mark read/unread
        if chapter.read:
            mark_btn = Gtk.Button(label="Mark as Unread")
            mark_btn.connect("clicked", lambda *_: (
                self._db.mark_chapter_unread(chapter.id),
                pop.popdown(),
                self._render_chapters()
            ))
        else:
            mark_btn = Gtk.Button(label="Mark as Read")
            mark_btn.connect("clicked", lambda *_: (
                self._db.mark_chapter_read(chapter.id),
                pop.popdown(),
                self._render_chapters()
            ))
        mark_btn.add_css_class("flat")
        box.append(mark_btn)

        # Download
        if chapter.download_status != DownloadStatus.DOWNLOADED:
            dl_btn = Gtk.Button(label="Download")
            dl_btn.add_css_class("flat")
            dl_btn.connect("clicked", lambda *_: (
                self._download_chapter(chapter),
                pop.popdown()
            ))
            box.append(dl_btn)

        pop.set_child(box)
        return pop

    # ── External web / tracking / migration ──────────────────────────────

    def _ensure_manga_persisted(self) -> bool:
        if not self._manga:
            return False
        if self._manga.id is None:
            self._manga.id = self._db.upsert_manga(self._manga)
        return self._manga.id is not None

    def _refresh_tracking_summary(self):
        if not self._manga or not self._manga.id:
            self._tracking_summary.set_text("Tracking: none")
            self._tracking_cache = {}
            return
        rows = self._db.get_manga_tracking(self._manga.id)
        self._tracking_cache = {r["provider"]: r for r in rows}
        if not rows:
            self._tracking_summary.set_text("Tracking: none")
            return
        manager = get_track_manager()
        parts = []
        for row in rows:
            service = manager.get_service(row["provider"])
            name = service.name if service else row["provider"]
            status = STATUS_LABELS.get(row.get("status") or "", row.get("status") or "Linked")
            progress = float(row.get("progress") or 0)
            total = float(row.get("total_chapters") or 0)
            counter = f"{progress:g}/{total:g}" if total else f"{progress:g}"
            parts.append(f"{name}: {status} ({counter})")
        self._tracking_summary.set_text("Tracking: " + "  •  ".join(parts))

    def _open_tracking_dialog(self, *_):
        """
        Manage this manga's tracker links.

        One section per registered service. A service the user is not logged
        in to says so and offers nothing else; a linked one shows editable
        status, progress and score, plus refresh and unlink.
        """
        if not self._ensure_manga_persisted():
            return
        root = self.get_root()
        if not isinstance(root, Gtk.Window):
            return

        dialog = Adw.Window(
            transient_for=root,
            modal=True,
            title="Tracking",
            default_width=520,
            default_height=600,
        )
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title="Tracking", subtitle=self._manga.title or ""
        ))
        toolbar.add_top_bar(header)

        self._track_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._track_body.set_margin_start(16)
        self._track_body.set_margin_end(16)
        self._track_body.set_margin_top(16)
        self._track_body.set_margin_bottom(16)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self._track_body)
        toolbar.set_content(scroll)

        self._track_status_label = Gtk.Label(label="")
        self._track_status_label.add_css_class("dim-label")
        self._track_status_label.set_wrap(True)
        self._track_status_label.set_margin_start(16)
        self._track_status_label.set_margin_end(16)
        self._track_status_label.set_margin_bottom(8)
        toolbar.add_bottom_bar(self._track_status_label)

        dialog.set_content(toolbar)
        self._track_dialog = dialog
        self._rebuild_tracking_sections()
        dialog.present()

    def _rebuild_tracking_sections(self):
        """Redraw every service section from the current local state."""
        if not hasattr(self, "_track_body"):
            return

        child = self._track_body.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._track_body.remove(child)
            child = nxt

        manager = get_track_manager()
        entries = {e.provider: e for e in manager.entries_for(self._manga.id)}
        self._tracking_cache = entries

        for service in manager.services:
            self._track_body.append(
                self._build_tracking_section(manager, service, entries.get(service.id))
            )

        pending = manager.queue.count()
        if pending:
            note = Gtk.Label(
                label=f"{pending} update(s) waiting to be sent. They retry automatically."
            )
            note.add_css_class("dim-label")
            note.set_wrap(True)
            note.set_xalign(0)
            self._track_body.append(note)

    def _build_tracking_section(self, manager, service, entry):
        group = Adw.PreferencesGroup(title=service.name)

        if not service.is_logged_in:
            row = Adw.ActionRow(
                title="Not logged in",
                subtitle=f"Log in to {service.name} from More \u2192 Tracking.",
            )
            group.add(row)
            return group

        if entry is None or not entry.remote_id:
            row = Adw.ActionRow(
                title="Not linked",
                subtitle=f"Search {service.name} for a matching entry.",
            )
            link_btn = Gtk.Button(label="Search\u2026")
            link_btn.add_css_class("suggested-action")
            link_btn.set_valign(Gtk.Align.CENTER)
            link_btn.connect(
                "clicked", lambda *_b, sv=service: self._open_track_search(sv)
            )
            row.add_suffix(link_btn)
            group.add(row)
            return group

        title_row = Adw.ActionRow(title=entry.title or "Linked entry")
        total = f"{entry.total_chapters:g}" if entry.total_chapters else "?"
        title_row.set_subtitle(f"{entry.progress:g} / {total} chapters")
        if entry.url:
            open_btn = Gtk.Button(icon_name="web-browser-symbolic")
            open_btn.add_css_class("flat")
            open_btn.set_valign(Gtk.Align.CENTER)
            open_btn.set_tooltip_text("Open on the tracker")
            open_btn.connect("clicked", lambda *_b, u=entry.url: webbrowser.open(u))
            title_row.add_suffix(open_btn)
        group.add(title_row)

        status_row = Adw.ComboRow(title="Status")
        status_model = Gtk.StringList()
        for status in ALL_STATUSES:
            status_model.append(STATUS_LABELS[status])
        status_row.set_model(status_model)
        if entry.status in ALL_STATUSES:
            status_row.set_selected(ALL_STATUSES.index(entry.status))
        status_row.connect(
            "notify::selected",
            lambda row, _p, sv=service, e=entry: self._on_track_status_changed(sv, e, row),
        )
        group.add(status_row)

        progress_row = Adw.SpinRow.new_with_range(0, 100000, 1)
        progress_row.set_title("Chapters read")
        progress_row.set_value(entry.progress)
        progress_row.connect(
            "notify::value",
            lambda row, _p, sv=service, e=entry: self._on_track_progress_changed(sv, e, row),
        )
        group.add(progress_row)

        score_row = Adw.SpinRow.new_with_range(0, service.max_score, 0.5)
        score_row.set_title("Score")
        score_row.set_digits(1)
        score_row.set_value(entry.score)
        score_row.connect(
            "notify::value",
            lambda row, _p, sv=service, e=entry: self._on_track_score_changed(sv, e, row),
        )
        group.add(score_row)

        actions_row = Adw.ActionRow(title="Manage")
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.set_valign(Gtk.Align.CENTER)
        refresh_btn.set_tooltip_text("Pull the current state from the tracker")
        refresh_btn.connect("clicked", lambda *_b, sv=service: self._on_track_refresh(sv))
        actions_row.add_suffix(refresh_btn)

        unlink_btn = Gtk.Button(label="Unlink")
        unlink_btn.add_css_class("destructive-action")
        unlink_btn.set_valign(Gtk.Align.CENTER)
        unlink_btn.set_tooltip_text(
            "Remove the local link. The entry on the tracker is left alone."
        )
        unlink_btn.connect("clicked", lambda *_b, sv=service: self._on_track_unlink(sv))
        actions_row.add_suffix(unlink_btn)
        group.add(actions_row)

        return group

    # ── Tracking actions ──────────────────────────────────────────────────

    def _set_tracking_dialog_status(self, text: str):
        if hasattr(self, "_track_status_label"):
            self._track_status_label.set_text(text)

    def _run_tracking_task(self, description: str, work, on_done=None):
        """Run a blocking tracker call off the main thread and report it."""
        self._set_tracking_dialog_status(f"{description}\u2026")

        def runner():
            try:
                result = work()
            except Exception as exc:
                GLib.idle_add(self._on_tracking_task_done, description, None, str(exc), on_done)
                return
            GLib.idle_add(self._on_tracking_task_done, description, result, None, on_done)

        threading.Thread(target=runner, daemon=True).start()

    def _on_tracking_task_done(self, description, result, error, on_done):
        if error is not None:
            self._set_tracking_dialog_status(f"{description} failed: {error}")
            notify_error(self, f"{description} failed: {error}")
            return False

        self._set_tracking_dialog_status(f"{description} done.")
        if on_done is not None:
            on_done(result)
        self._rebuild_tracking_sections()
        self._refresh_tracking_summary()
        return False

    def _on_track_status_changed(self, service, entry, row):
        status = ALL_STATUSES[row.get_selected()]
        if status == entry.status:
            return
        updated = TrackEntry(**entry.__dict__)
        updated.status = status
        self._push_track_entry(service, updated, "Updating status")

    def _on_track_progress_changed(self, service, entry, row):
        progress = float(row.get_value())
        if progress == entry.progress:
            return
        updated = TrackEntry(**entry.__dict__)
        updated.progress = progress
        self._push_track_entry(service, updated, "Updating progress")

    def _on_track_score_changed(self, service, entry, row):
        score = float(row.get_value())
        if score == entry.score:
            return
        updated = TrackEntry(**entry.__dict__)
        updated.score = score
        self._push_track_entry(service, updated, "Updating score")

    def _push_track_entry(self, service, entry, description):
        manga_id = self._manga.id
        self._run_tracking_task(
            description,
            lambda: get_track_manager().set_entry(manga_id, entry),
        )

    def _on_track_refresh(self, service):
        manga_id = self._manga.id
        self._run_tracking_task(
            f"Refreshing {service.name}",
            lambda: get_track_manager().pull(manga_id),
        )

    def _on_track_unlink(self, service):
        manga_id = self._manga.id
        self._run_tracking_task(
            f"Unlinking {service.name}",
            lambda: get_track_manager().unlink(manga_id, service.id),
        )

    def _open_track_search(self, service):
        """Search the tracker for an entry to link this manga to."""
        root = self.get_root()
        dialog = Adw.Window(
            transient_for=root,
            modal=True,
            title=f"Link on {service.name}",
            default_width=520,
            default_height=560,
        )
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=f"Link on {service.name}"))
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.set_margin_start(16)
        body.set_margin_end(16)
        body.set_margin_top(16)
        body.set_margin_bottom(16)

        entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        query_entry = Gtk.SearchEntry()
        query_entry.set_hexpand(True)
        query_entry.set_text(self._manga.title or "")
        entry_row.append(query_entry)
        search_btn = Gtk.Button(label="Search")
        search_btn.add_css_class("suggested-action")
        entry_row.append(search_btn)
        body.append(entry_row)

        status = Gtk.Label(label="")
        status.add_css_class("dim-label")
        status.set_xalign(0)
        status.set_wrap(True)
        body.append(status)

        results = Gtk.ListBox()
        results.set_selection_mode(Gtk.SelectionMode.NONE)
        results.add_css_class("boxed-list")
        body.append(results)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(body)
        toolbar.set_content(scroll)
        dialog.set_content(toolbar)

        def clear_results():
            child = results.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                results.remove(child)
                child = nxt

        def on_results(found):
            clear_results()
            if not found:
                status.set_text("No matches.")
                return False
            status.set_text(f"{len(found)} match(es). Pick one to link.")
            for candidate in found:
                row = Adw.ActionRow(title=candidate.title or "Untitled")
                bits = []
                if candidate.start_date:
                    bits.append(candidate.start_date)
                if candidate.total_chapters:
                    bits.append(f"{candidate.total_chapters:g} chapters")
                if candidate.publishing_status:
                    bits.append(candidate.publishing_status)
                row.set_subtitle("  \u2022  ".join(bits))

                link_btn = Gtk.Button(label="Link")
                link_btn.add_css_class("suggested-action")
                link_btn.set_valign(Gtk.Align.CENTER)
                link_btn.connect(
                    "clicked",
                    lambda *_b, c=candidate: (
                        dialog.close(),
                        self._link_track_entry(service, c),
                    ),
                )
                row.add_suffix(link_btn)
                results.append(row)
            return False

        def on_error(message):
            clear_results()
            status.set_text(f"Search failed: {message}")
            return False

        def do_search(*_):
            query = query_entry.get_text().strip()
            if not query:
                return
            status.set_text("Searching\u2026")
            clear_results()

            def work():
                try:
                    found = service.search(query)
                except Exception as exc:
                    GLib.idle_add(on_error, str(exc))
                    return
                GLib.idle_add(on_results, found)

            threading.Thread(target=work, daemon=True).start()

        search_btn.connect("clicked", do_search)
        query_entry.connect("activate", do_search)

        dialog.present()
        do_search()

    def _link_track_entry(self, service, candidate):
        manga_id = self._manga.id
        self._run_tracking_task(
            f"Linking to {candidate.title}",
            lambda: get_track_manager().link(manga_id, service.id, candidate.remote_id),
        )

    def _open_migration_dialog(self, *_):
        if not self._manga:
            return
        root = self.get_root()
        if not isinstance(root, Gtk.Window):
            return

        dialog = Gtk.Dialog(title="Migrate Manga", transient_for=root, modal=True)
        dialog.set_default_size(640, 520)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.connect("response", lambda d, _r: d.close())

        area = dialog.get_content_area()
        area.set_margin_start(12)
        area.set_margin_end(12)
        area.set_margin_top(12)
        area.set_margin_bottom(12)
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        area.append(wrap)

        hint = Gtk.Label(label="Find matching manga on other sources and migrate progress/categories.")
        hint.add_css_class("dim-label")
        hint.set_xalign(0)
        wrap.append(hint)

        self._migrate_query_entry = Gtk.SearchEntry()
        self._migrate_query_entry.set_placeholder_text("Search query (supports src: and id:)")
        self._migrate_query_entry.set_text(self._manga.title or "")
        self._migrate_query_entry.connect("activate", self._start_migration_search)
        wrap.append(self._migrate_query_entry)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._migrate_search_btn = Gtk.Button(label="Search Targets")
        self._migrate_search_btn.add_css_class("suggested-action")
        self._migrate_search_btn.connect("clicked", self._start_migration_search)
        search_row.append(self._migrate_search_btn)

        self._migrate_keep_old_cb = Gtk.CheckButton(label="Keep old manga in library")
        self._migrate_keep_old_cb.set_active(True)
        search_row.append(self._migrate_keep_old_cb)
        wrap.append(search_row)

        self._migrate_status = Gtk.Label(label="Ready")
        self._migrate_status.add_css_class("dim-label")
        self._migrate_status.set_xalign(0)
        wrap.append(self._migrate_status)

        self._migrate_results = Gtk.ListBox()
        self._migrate_results.set_selection_mode(Gtk.SelectionMode.NONE)
        self._migrate_results.add_css_class("boxed-list")
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self._migrate_results)
        wrap.append(scroll)

        dialog.present()

    def _start_migration_search(self, *_):
        if not hasattr(self, "_migrate_search_btn"):
            return
        query_raw = self._migrate_query_entry.get_text().strip()
        query, src_filter, id_filter = self._parse_source_filters(query_raw)
        if not query:
            self._migrate_status.set_text("Enter a query to search migration targets.")
            return

        registry = get_registry()
        sources = []
        for ext in registry.get_all():
            if self._manga and ext.id == self._manga.source_id:
                continue
            if id_filter and ext.id.lower() != id_filter:
                continue
            if src_filter and src_filter not in ext.name.lower() and src_filter not in ext.id.lower():
                continue
            sources.append(ext)

        if not sources:
            self._migrate_status.set_text("No sources matched filters.")
            return

        self._migrate_search_btn.set_sensitive(False)
        self._migrate_status.set_text(f"Searching {len(sources)} sources...")
        self._clear_migration_results()

        def run():
            rows = []
            errors = 0
            total = len(sources)
            for i, ext in enumerate(sources, start=1):
                GLib.idle_add(self._migrate_status.set_text, f"Searching {i}/{total}: {ext.name}")
                try:
                    mangas, _ = ext.search(SearchFilter(query=query), page=1)
                    for m in mangas[:10]:
                        if not m.source_id:
                            m.source_id = ext.id
                        if not m.source_manga_id:
                            m.source_manga_id = m.url or m.title
                        rows.append((ext, m))
                except Exception:
                    errors += 1
            dedup = []
            seen = set()
            for ext, m in rows:
                key = (m.source_id, m.source_manga_id or m.url or m.title)
                if key in seen:
                    continue
                seen.add(key)
                dedup.append((ext, m))
            GLib.idle_add(self._on_migration_search_done, dedup, errors)

        threading.Thread(target=run, daemon=True).start()

    def _on_migration_search_done(self, results, errors: int):
        self._migrate_search_btn.set_sensitive(True)
        if not results:
            self._migrate_status.set_text("No migration targets found.")
            return
        for ext, manga in results:
            row = Adw.ActionRow(title=manga.title or "Untitled")
            subtitle = ext.name
            if manga.author:
                subtitle += f"  •  {manga.author}"
            row.set_subtitle(subtitle)

            migrate_btn = Gtk.Button(label="Migrate")
            migrate_btn.add_css_class("suggested-action")
            migrate_btn.connect("clicked", lambda *_b, e=ext, m=manga: self._run_migration(e, m))
            row.add_suffix(migrate_btn)
            self._migrate_results.append(row)
        if errors:
            self._migrate_status.set_text(f"Found {len(results)} targets ({errors} sources failed).")
        else:
            self._migrate_status.set_text(f"Found {len(results)} targets.")

    def _clear_migration_results(self):
        if not hasattr(self, "_migrate_results"):
            return
        child = self._migrate_results.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._migrate_results.remove(child)
            child = nxt

    def _run_migration(self, ext, target_manga: Manga):
        if not self._ensure_manga_persisted():
            return
        old_manga = self._manga
        old_manga_id = old_manga.id
        keep_old = self._migrate_keep_old_cb.get_active() if hasattr(self, "_migrate_keep_old_cb") else True
        self._migrate_status.set_text(f"Migrating to {ext.name}...")

        def run():
            try:
                candidate = ext.get_manga_details(target_manga)
            except Exception:
                candidate = target_manga
            candidate.source_id = ext.id
            if not candidate.source_manga_id:
                candidate.source_manga_id = candidate.url or candidate.title
            candidate.in_library = old_manga.in_library
            candidate.reading_status = old_manga.reading_status
            candidate.added_at = old_manga.added_at or time.time()
            new_id = self._db.upsert_manga(candidate)
            candidate.id = new_id

            if old_manga.in_library:
                self._db.add_to_library(new_id)
            self._db.update_reading_status(new_id, old_manga.reading_status)
            if old_manga_id:
                self._db.copy_manga_categories(old_manga_id, new_id)

            try:
                chapters = ext.get_chapters(candidate)
            except Exception:
                chapters = []
            for ch in chapters:
                ch.manga_id = new_id
            if chapters:
                self._db.upsert_chapters(chapters)
            if old_manga_id:
                self._db.copy_chapter_progress_by_number(old_manga_id, new_id)

            if old_manga_id and not keep_old and old_manga.in_library:
                self._db.remove_from_library(old_manga_id)

            new_manga = self._db.get_manga_by_id(new_id) or candidate
            GLib.idle_add(self._on_migration_complete, new_manga, ext.name)

        threading.Thread(target=run, daemon=True).start()

    def _on_migration_complete(self, manga: Manga, source_name: str):
        self.load_manga(manga)
        if hasattr(self, "_migrate_status"):
            self._migrate_status.set_text(f"Migration complete. Now viewing {source_name}.")

    @staticmethod
    def _parse_source_filters(raw_query: str):
        query_terms = []
        src_filter = ""
        id_filter = ""
        for token in raw_query.split():
            lower = token.lower()
            if lower.startswith("src:") and len(token) > 4:
                src_filter = token[4:].strip().lower()
            elif lower.startswith("id:") and len(token) > 3:
                id_filter = token[3:].strip().lower()
            else:
                query_terms.append(token)
        return " ".join(query_terms).strip(), src_filter, id_filter

    def _on_read_clicked(self, btn, chapter: Chapter):
        if self._on_read_chapter:
            self._on_read_chapter(self._manga, chapter)

    def _continue_reading(self, *_):
        if not self._chapters:
            return
        # Find first unread chapter
        sorted_chapters = sorted(self._chapters, key=lambda c: c.chapter_number)
        for ch in sorted_chapters:
            if not ch.read:
                if self._on_read_chapter:
                    self._on_read_chapter(self._manga, ch)
                return
        # All read, start from beginning
        if sorted_chapters and self._on_read_chapter:
            self._on_read_chapter(self._manga, sorted_chapters[0])

    def _toggle_library(self, *_):
        if not self._manga:
            return
        db = self._db
        if self._manga.in_library:
            db.remove_from_library(self._manga.id)
            self._manga.in_library = False
        else:
            if self._manga.id is None:
                # Save to DB first
                manga_id = db.upsert_manga(self._manga)
                self._manga.id = manga_id
            db.add_to_library(self._manga.id)
            self._manga.in_library = True
        self._update_library_button()

    def _update_library_button(self):
        if self._manga and self._manga.in_library:
            self._library_btn.set_label("In Library")
            self._library_btn.set_icon_name("heart-filled-symbolic")
            self._library_btn.remove_css_class("suggested-action")
            self._library_btn.add_css_class("flat")
        else:
            self._library_btn.set_label("Add to Library")
            self._library_btn.set_icon_name("heart-outline-thick-symbolic")
            self._library_btn.add_css_class("suggested-action")
            self._library_btn.remove_css_class("flat")

    def _set_reading_status(self, btn, status: ReadingStatus, popover):
        if not self._manga:
            return
        if not self._manga.id and not self._ensure_manga_persisted():
            return
        self._db.update_reading_status(self._manga.id, status)
        self._manga.reading_status = status
        popover.popdown()

    def _mark_all_read(self, *_):
        for ch in self._chapters:
            if not ch.read:
                self._db.mark_chapter_read(ch.id)
                ch.read = True
        self._render_chapters()

    def _sort_chapters(self, chapters):
        """
        Order chapters by the selected mode.

        "Descending" always means the direction a reader expects for that
        mode: newest chapter first. Source order is already newest-first as
        the source returned it, so descending leaves it alone.
        """
        if self._chapter_sort == "source":
            ordered = sorted(chapters, key=lambda c: c.source_order)
            return ordered if self._sort_descending else list(reversed(ordered))

        if self._chapter_sort == "upload":
            key = lambda c: (c.uploaded_at or 0, c.chapter_number)
        else:
            key = lambda c: (c.chapter_number, c.source_order)

        return sorted(chapters, key=key, reverse=self._sort_descending)

    def _set_chapter_sort(self, btn, mode):
        if not btn.get_active() or mode == self._chapter_sort:
            return
        self._chapter_sort = mode
        self._render_chapters()

    def _toggle_sort(self, btn):
        self._sort_descending = btn.get_active()
        self._render_chapters()

    def _download_chapter(self, chapter: Chapter):
        ext = get_registry().get(self._manga.source_id)
        if not ext:
            return

        def fetch_and_queue():
            try:
                pages = ext.get_pages(chapter)
                dm = get_download_manager()
                dm.enqueue(self._manga, chapter, pages)
            except Exception as e:
                logger.error("download error: %s", e)

        threading.Thread(target=fetch_and_queue, daemon=True).start()

    def _download_unread(self):
        if not self._chapters:
            return
        for ch in self._chapters:
            if not ch.read and ch.download_status != DownloadStatus.DOWNLOADED:
                self._download_chapter(ch)
                
    def _download_all_chapters(self):
        if not self._chapters:
            return
        for ch in self._chapters:
            if ch.download_status != DownloadStatus.DOWNLOADED:
                self._download_chapter(ch)
