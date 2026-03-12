"""
Manga detail view - shows manga info, chapter list, add to library.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, GdkPixbuf, Pango
import threading
import time
from ..core.database import get_db
from ..core.models import Manga, Chapter, ReadingStatus, DownloadStatus
from ..core import image_loader
from ..extensions.registry import get_registry
from ..core.downloader import get_download_manager


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

        # WebView / Browse
        web_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        web_btn = Gtk.Button(icon_name="web-browser-symbolic")
        web_btn.add_css_class("circular")
        web_btn.set_size_request(48, 48)
        web_btn.set_halign(Gtk.Align.CENTER)
        web_box.append(web_btn)
        web_lbl = Gtk.Label(label="WebView")
        web_lbl.add_css_class("caption")
        web_box.append(web_lbl)
        action_box.append(web_box)

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
        sort_btn.set_tooltip_text("Sort chapters")
        sort_btn.set_active(True)
        sort_btn.connect("toggled", self._toggle_sort)
        self._sort_descending = True
        ch_header.append(sort_btn)

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

    def load_manga(self, manga: Manga):
        """Load and display a manga's details."""
        self._manga = manga
        self._manga_title.set_text(manga.title)
        self._author_label.set_text(manga.author or "Unknown Author")
        self._status_label.set_markup(
            f"<b>Status:</b> {manga.status.title() if manga.status else 'Unknown'}"
        )
        self._description.set_text(manga.description or "No description available.")
        if manga.score:
            self._score_label.set_text(f"⭐ {manga.score:.1f}/10")

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

        # Load cover
        url = manga.cover_local_path or manga.cover_url
        if url:
            image_loader.load_image_async(
                url,
                self._on_cover_loaded,
                width=320, height=480,  # Higher resolution for the blurred background
            )

        # Load details + chapters in background
        self._load_details()

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
                # Get full details
                updated = ext.get_manga_details(manga)
                # Update DB
                db_id = self._db.upsert_manga(updated)
                updated.id = db_id

                # Get chapters
                chapters = ext.get_chapters(updated)
                for ch in chapters:
                    ch.manga_id = db_id
                self._db.upsert_chapters(chapters)
                # Re-fetch from DB to get IDs
                db_chapters = self._db.get_chapters(db_id)
                GLib.idle_add(self._on_details_loaded, updated, db_chapters)
            except Exception as e:
                print(f"[detail] Error loading details: {e}")
                # Still try to show cached chapters
                if manga.id:
                    db_chapters = self._db.get_chapters(manga.id)
                    GLib.idle_add(self._on_details_loaded, manga, db_chapters)

        threading.Thread(target=fetch, daemon=True).start()

    def _on_details_loaded(self, manga: Manga, chapters):
        self._manga = manga
        self._chapters = chapters
        self._chapter_count_label.set_text(f"{len(chapters)} Chapters")
        self._render_chapters()
        self._update_library_button()

    def _render_chapters(self):
        # Clear
        child = self._chapter_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._chapter_list.remove(child)
            child = nxt

        chapters = self._chapters
        if self._sort_descending:
            chapters = sorted(chapters, key=lambda c: c.chapter_number, reverse=True)
        else:
            chapters = sorted(chapters, key=lambda c: c.chapter_number)

        for chapter in chapters:
            row = self._make_chapter_row(chapter)
            self._chapter_list.append(row)

    def _make_chapter_row(self, chapter: Chapter) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_activatable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

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
        if not self._manga or not self._manga.id:
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
                print(f"[detail] Download error: {e}")

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
