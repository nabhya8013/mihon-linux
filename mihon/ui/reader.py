"""
Manga reader view - full-featured reader with paged/scroll/webtoon modes.
Supports RTL/LTR, zoom, keyboard navigation, and progress saving.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, GdkPixbuf, Gdk, GObject
import threading
import time
from ..core.database import get_db
from ..core.models import Manga, Chapter, Page, ReadingDirection
from ..core import image_loader
from ..extensions.registry import get_registry


class PageView(Gtk.ScrolledWindow):
    """Single page display widget."""

    def __init__(self):
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._picture = Gtk.Picture()
        self._picture.set_vexpand(True)
        self._picture.set_hexpand(True)
        self._picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._picture.add_css_class("reader-page")
        self.set_child(self._picture)

    def set_pixbuf(self, pixbuf):
        if pixbuf:
            self._picture.set_pixbuf(pixbuf)
        else:
            self._picture.set_pixbuf(None)

    def set_loading(self):
        self._picture.set_pixbuf(None)


class WebtoonView(Gtk.ScrolledWindow):
    """Continuous vertical scroll view for webtoons."""

    def __init__(self):
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._box.set_hexpand(True)
        viewport = Gtk.Viewport()
        viewport.set_child(self._box)
        self.set_child(viewport)
        self._page_widgets = []

    def set_pages(self, pages, on_page_visible=None):
        # Clear
        child = self._box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._box.remove(child)
            child = nxt
        self._page_widgets = []

        for i, page in enumerate(pages):
            pic = Gtk.Picture()
            pic.set_hexpand(True)
            pic.set_content_fit(Gtk.ContentFit.FILL)
            pic.set_size_request(-1, 800)
            self._box.append(pic)
            self._page_widgets.append(pic)

            # Load image
            url = page.image_url or page.url
            idx = i
            def make_cb(widget):
                def cb(pb):
                    if pb:
                        widget.set_pixbuf(pb)
                return cb
            image_loader.load_image_async(url, make_cb(pic))

    def scroll_to_page(self, page_idx):
        if 0 <= page_idx < len(self._page_widgets):
            widget = self._page_widgets[page_idx]
            adj = self.get_vadjustment()
            # Approximate scroll position
            total_height = adj.get_upper()
            pos = (page_idx / max(len(self._page_widgets), 1)) * total_height
            adj.set_value(pos)


class ReaderView(Gtk.Box):
    """
    Full manga reader with:
    - Paged mode (single/double page, RTL/LTR)
    - Webtoon/continuous scroll mode
    - Keyboard navigation
    - Zoom
    - Settings panel
    - Progress auto-save
    """

    def __init__(self, on_close=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_close = on_close
        self._manga: Manga = None
        self._chapter: Chapter = None
        self._pages = []
        self._current_page = 0
        self._loading = False
        self._direction = ReadingDirection.RTL
        self._mode = "paged"  # paged | webtoon
        self._zoom = 1.0
        self._ui_visible = True
        self._db = get_db()

        self._build_ui()
        self._setup_keyboard()

    def _build_ui(self):
        # Top bar (auto-hide)
        self._top_bar = Adw.HeaderBar()
        self._top_bar.add_css_class("reader-header")
        self._top_bar.set_show_end_title_buttons(False)

        back_btn = Gtk.Button(icon_name="go-previous-symbolic")
        back_btn.set_tooltip_text("Back to manga (Esc)")
        back_btn.connect("clicked", self._close)
        self._top_bar.pack_start(back_btn)

        self._chapter_title = Adw.WindowTitle()
        self._top_bar.set_title_widget(self._chapter_title)

        # Reader settings button
        settings_btn = Gtk.MenuButton(icon_name="preferences-system-symbolic")
        settings_btn.set_tooltip_text("Reader settings")
        settings_btn.set_popover(self._build_settings_popover())
        self._top_bar.pack_end(settings_btn)

        self.append(self._top_bar)

        # Main reader area
        self._reader_stack = Gtk.Stack()
        self._reader_stack.set_vexpand(True)
        self._reader_stack.set_transition_type(Gtk.StackTransitionType.NONE)

        # Paged view
        self._paged_overlay = Gtk.Overlay()
        self._paged_overlay.add_css_class("reader-bg")

        self._page_view = PageView()
        self._paged_overlay.set_child(self._page_view)

        # Loading spinner overlay
        self._page_spinner = Gtk.Spinner()
        self._page_spinner.set_size_request(48, 48)
        self._page_spinner.set_halign(Gtk.Align.CENTER)
        self._page_spinner.set_valign(Gtk.Align.CENTER)
        self._page_spinner.add_css_class("reader-spinner")
        self._paged_overlay.add_overlay(self._page_spinner)

        # Tap zones for navigation
        self._left_zone = Gtk.Button()
        self._left_zone.set_opacity(0)
        self._left_zone.set_size_request(120, -1)
        self._left_zone.set_halign(Gtk.Align.START)
        self._left_zone.set_valign(Gtk.Align.FILL)
        self._left_zone.set_vexpand(True)
        self._left_zone.connect("clicked", self._on_left_tap)
        self._paged_overlay.add_overlay(self._left_zone)

        self._right_zone = Gtk.Button()
        self._right_zone.set_opacity(0)
        self._right_zone.set_size_request(120, -1)
        self._right_zone.set_halign(Gtk.Align.END)
        self._right_zone.set_valign(Gtk.Align.FILL)
        self._right_zone.set_vexpand(True)
        self._right_zone.connect("clicked", self._on_right_tap)
        self._paged_overlay.add_overlay(self._right_zone)

        self._reader_stack.add_named(self._paged_overlay, "paged")

        # Webtoon view
        self._webtoon_view = WebtoonView()
        self._reader_stack.add_named(self._webtoon_view, "webtoon")

        self.append(self._reader_stack)

        # Bottom bar
        self._bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._bottom_bar.add_css_class("reader-bottom-bar")
        self._bottom_bar.set_margin_start(16)
        self._bottom_bar.set_margin_end(16)
        self._bottom_bar.set_margin_top(8)
        self._bottom_bar.set_margin_bottom(8)

        prev_btn = Gtk.Button(icon_name="go-previous-symbolic")
        prev_btn.connect("clicked", lambda *_: self._prev_page())
        prev_btn.set_tooltip_text("Previous page (← or A)")
        self._bottom_bar.append(prev_btn)

        self._page_label = Gtk.Label(label="0 / 0")
        self._page_label.set_hexpand(True)
        self._page_label.set_justify(Gtk.Justification.CENTER)
        self._bottom_bar.append(self._page_label)

        next_btn = Gtk.Button(icon_name="go-next-symbolic")
        next_btn.connect("clicked", lambda *_: self._next_page())
        next_btn.set_tooltip_text("Next page (→ or D)")
        self._bottom_bar.append(next_btn)

        self.append(self._bottom_bar)

        # Page slider (shown below bottom bar)
        self._slider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._slider_box.set_margin_start(16)
        self._slider_box.set_margin_end(16)
        self._slider_box.set_margin_bottom(8)

        self._slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL)
        self._slider.set_hexpand(True)
        self._slider.set_draw_value(False)
        self._slider.set_range(0, 1)
        self._slider.connect("value-changed", self._on_slider_changed)
        self._slider_box.append(self._slider)
        self._slider_changing = False

        self.append(self._slider_box)

    def _build_settings_popover(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_size_request(260, -1)

        # Reading direction
        dir_label = Gtk.Label(label="Reading Direction")
        dir_label.add_css_class("heading")
        dir_label.set_halign(Gtk.Align.START)
        box.append(dir_label)

        dir_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        dir_box.add_css_class("linked")

        self._rtl_btn = Gtk.ToggleButton(label="RTL")
        self._rtl_btn.set_active(True)
        self._rtl_btn.set_hexpand(True)
        self._rtl_btn.connect("toggled", self._set_direction, ReadingDirection.RTL)
        dir_box.append(self._rtl_btn)

        self._ltr_btn = Gtk.ToggleButton(label="LTR")
        self._ltr_btn.set_group(self._rtl_btn)
        self._ltr_btn.set_hexpand(True)
        self._ltr_btn.connect("toggled", self._set_direction, ReadingDirection.LTR)
        dir_box.append(self._ltr_btn)

        self._webtoon_btn = Gtk.ToggleButton(label="Webtoon")
        self._webtoon_btn.set_group(self._rtl_btn)
        self._webtoon_btn.set_hexpand(True)
        self._webtoon_btn.connect("toggled", self._set_direction, ReadingDirection.WEBTOON)
        dir_box.append(self._webtoon_btn)

        box.append(dir_box)

        # Background color
        bg_label = Gtk.Label(label="Background")
        bg_label.add_css_class("heading")
        bg_label.set_halign(Gtk.Align.START)
        box.append(bg_label)

        bg_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bg_box.add_css_class("linked")

        black_btn = Gtk.ToggleButton(label="Black")
        black_btn.set_active(True)
        black_btn.set_hexpand(True)
        black_btn.connect("toggled", self._set_bg, "black")
        bg_box.append(black_btn)

        white_btn = Gtk.ToggleButton(label="White")
        white_btn.set_group(black_btn)
        white_btn.set_hexpand(True)
        white_btn.connect("toggled", self._set_bg, "white")
        bg_box.append(white_btn)

        gray_btn = Gtk.ToggleButton(label="Gray")
        gray_btn.set_group(black_btn)
        gray_btn.set_hexpand(True)
        gray_btn.connect("toggled", self._set_bg, "gray")
        bg_box.append(gray_btn)

        box.append(bg_box)

        # Zoom
        zoom_label = Gtk.Label(label="Zoom")
        zoom_label.add_css_class("heading")
        zoom_label.set_halign(Gtk.Align.START)
        box.append(zoom_label)

        zoom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        zoom_out = Gtk.Button(icon_name="zoom-out-symbolic")
        zoom_out.connect("clicked", lambda *_: self._set_zoom(self._zoom - 0.1))
        zoom_row.append(zoom_out)

        self._zoom_label = Gtk.Label(label="100%")
        self._zoom_label.set_hexpand(True)
        self._zoom_label.set_justify(Gtk.Justification.CENTER)
        zoom_row.append(self._zoom_label)

        zoom_in = Gtk.Button(icon_name="zoom-in-symbolic")
        zoom_in.connect("clicked", lambda *_: self._set_zoom(self._zoom + 0.1))
        zoom_row.append(zoom_in)

        zoom_fit = Gtk.Button(label="Fit")
        zoom_fit.connect("clicked", lambda *_: self._set_zoom(1.0))
        zoom_row.append(zoom_fit)
        box.append(zoom_row)

        pop.set_child(box)
        return pop

    def _setup_keyboard(self):
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        if keyval in (Gdk.KEY_Right, Gdk.KEY_d, Gdk.KEY_D):
            if self._direction == ReadingDirection.RTL:
                self._prev_page()
            else:
                self._next_page()
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_a, Gdk.KEY_A):
            if self._direction == ReadingDirection.RTL:
                self._next_page()
            else:
                self._prev_page()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_s, Gdk.KEY_S, Gdk.KEY_space):
            if self._mode == "webtoon":
                adj = self._webtoon_view.get_vadjustment()
                adj.set_value(adj.get_value() + adj.get_page_increment())
            else:
                self._next_page()
            return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_w, Gdk.KEY_W):
            if self._mode == "webtoon":
                adj = self._webtoon_view.get_vadjustment()
                adj.set_value(adj.get_value() - adj.get_page_increment())
            else:
                self._prev_page()
            return True
        if keyval == Gdk.KEY_Escape:
            self._close()
            return True
        return False

    def load_chapter(self, manga: Manga, chapter: Chapter):
        """Load a chapter for reading."""
        self._manga = manga
        self._chapter = chapter
        self._pages = []
        self._current_page = 0

        ch_num = f"Ch.{chapter.chapter_number:g}" if chapter.chapter_number >= 0 else chapter.title
        self._chapter_title.set_title(manga.title)
        self._chapter_title.set_subtitle(ch_num)
        self._page_label.set_text("Loading...")

        self._page_spinner.start()
        self._page_spinner.set_visible(True)

        ext = get_registry().get(manga.source_id)
        if not ext:
            return

        def fetch():
            try:
                # Check if downloaded locally
                if chapter.local_path:
                    import os
                    from pathlib import Path
                    path = Path(chapter.local_path)
                    if path.exists():
                        files = sorted([
                            f for f in path.iterdir()
                            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".avif")
                        ])
                        pages = []
                        for i, f in enumerate(files):
                            p = Page(index=i, url=str(f), image_url=str(f), local_path=str(f))
                            pages.append(p)
                        GLib.idle_add(self._on_pages_loaded, pages)
                        return

                pages = ext.get_pages(chapter)
                GLib.idle_add(self._on_pages_loaded, pages)
            except Exception as e:
                GLib.idle_add(self._on_load_error, str(e))

        threading.Thread(target=fetch, daemon=True).start()

    def _on_pages_loaded(self, pages):
        self._pages = pages
        self._page_spinner.stop()
        self._page_spinner.set_visible(False)

        if not pages:
            self._page_label.set_text("No pages found")
            return

        # Restore last page
        if self._chapter.last_page_read > 0:
            self._current_page = min(self._chapter.last_page_read, len(pages) - 1)
        else:
            self._current_page = 0

        # Setup slider
        self._slider.set_range(0, max(len(pages) - 1, 1))
        self._slider.set_increments(1, 1)

        if self._mode == "webtoon":
            self._webtoon_view.set_pages(pages)
            self._reader_stack.set_visible_child_name("webtoon")
        else:
            self._reader_stack.set_visible_child_name("paged")
            self._show_page(self._current_page)

    def _on_load_error(self, message):
        self._page_spinner.stop()
        self._page_spinner.set_visible(False)
        self._page_label.set_text(f"Error: {message}")
        print(f"[reader] Error: {message}")

    def _show_page(self, idx):
        if not self._pages or idx < 0 or idx >= len(self._pages):
            return
        self._current_page = idx
        page = self._pages[idx]
        self._page_label.set_text(f"{idx + 1} / {len(self._pages)}")

        # Update slider without triggering callback
        self._slider_changing = True
        self._slider.set_value(idx)
        self._slider_changing = False

        # Save progress
        self._save_progress(idx)

        # Load image
        self._page_view.set_loading()
        url = page.local_path or page.image_url or page.url
        if page.local_path:
            pixbuf = image_loader.load_local_image(page.local_path)
            self._page_view.set_pixbuf(pixbuf)
        else:
            image_loader.load_image_async(
                url,
                self._page_view.set_pixbuf,
            )

    def _next_page(self):
        if self._current_page < len(self._pages) - 1:
            self._show_page(self._current_page + 1)
        else:
            self._on_chapter_finished()

    def _prev_page(self):
        if self._current_page > 0:
            self._show_page(self._current_page - 1)

    def _on_left_tap(self, *_):
        if self._direction == ReadingDirection.RTL:
            self._next_page()
        else:
            self._prev_page()

    def _on_right_tap(self, *_):
        if self._direction == ReadingDirection.RTL:
            self._prev_page()
        else:
            self._next_page()

    def _on_slider_changed(self, slider):
        if self._slider_changing:
            return
        idx = int(slider.get_value())
        if idx != self._current_page:
            self._show_page(idx)

    def _on_chapter_finished(self):
        """All pages read — mark chapter as read."""
        if self._chapter and self._chapter.id:
            self._db.mark_chapter_read(self._chapter.id, len(self._pages) - 1)
            self._chapter.read = True

    def _save_progress(self, page_idx: int):
        if self._chapter and self._chapter.id and self._manga and self._manga.id:
            self._db.update_chapter_progress(self._chapter.id, page_idx)
            self._db.record_history(self._manga.id, self._chapter.id, page_idx)

    def _set_direction(self, btn, direction: ReadingDirection):
        if not btn.get_active():
            return
        self._direction = direction
        if direction == ReadingDirection.WEBTOON:
            self._mode = "webtoon"
            if self._pages:
                self._webtoon_view.set_pages(self._pages)
            self._reader_stack.set_visible_child_name("webtoon")
            self._bottom_bar.set_visible(False)
            self._slider_box.set_visible(False)
        else:
            self._mode = "paged"
            self._reader_stack.set_visible_child_name("paged")
            self._bottom_bar.set_visible(True)
            self._slider_box.set_visible(True)
            if self._pages:
                self._show_page(self._current_page)

    def _set_bg(self, btn, color):
        if not btn.get_active():
            return
        css_map = {
            "black": "background-color: #000;",
            "white": "background-color: #fff;",
            "gray": "background-color: #333;",
        }
        # Apply via CSS provider
        provider = Gtk.CssProvider()
        provider.load_from_string(f".reader-bg {{ {css_map.get(color, '')} }}")
        display = self.get_display()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )

    def _set_zoom(self, zoom):
        self._zoom = max(0.3, min(3.0, zoom))
        self._zoom_label.set_text(f"{int(self._zoom * 100)}%")
        # Zoom is handled by page widget resize
        if self._pages:
            self._show_page(self._current_page)

    def _close(self, *_):
        if self._on_close:
            self._on_close()
