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
from ..core.page_cache import (
    AUTO_DOUBLE_MIN_WIDTH,
    PageCache,
    pixbuf_is_spread,
    should_auto_double,
)
from ..extensions.registry import get_registry
from ..core.tracking import TrackManager, get_track_manager
from .notify import notify_retry
import logging

logger = logging.getLogger("reader")


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
        self._content_fit = Gtk.ContentFit.CONTAIN

    def set_pixbuf(self, pixbuf):
        if pixbuf:
            self._picture.set_pixbuf(pixbuf)
        else:
            self._picture.set_pixbuf(None)

    def set_loading(self):
        self._picture.set_pixbuf(None)

    def set_content_fit(self, fit):
        self._content_fit = fit
        self._picture.set_content_fit(fit)


class DoublePageView(Gtk.ScrolledWindow):
    """Two-page spread display for paged mode."""

    def __init__(self):
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._box.set_halign(Gtk.Align.CENTER)
        self._box.set_valign(Gtk.Align.CENTER)
        self.set_child(self._box)

        self._left = Gtk.Picture()
        self._right = Gtk.Picture()
        for pic in (self._left, self._right):
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.set_vexpand(True)
            pic.set_hexpand(True)
            pic.add_css_class("reader-page")
            self._box.append(pic)

    def set_pixbufs(self, left, right):
        self._left.set_pixbuf(left if left else None)
        self._right.set_pixbuf(right if right else None)
        self._right.set_visible(right is not None)

    def set_spread(self, pixbuf):
        """Show one landscape image across the whole viewport, unpaired."""
        self._left.set_pixbuf(pixbuf if pixbuf else None)
        self._right.set_pixbuf(None)
        self._right.set_visible(False)

    def set_loading(self):
        self._left.set_pixbuf(None)
        self._right.set_pixbuf(None)

    def set_content_fit(self, fit):
        self._left.set_content_fit(fit)
        self._right.set_content_fit(fit)


class WebtoonView(Gtk.ScrolledWindow):
    """Continuous vertical scroll view for webtoons."""

    def __init__(self):
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # No spacing: webtoon panels are cut from one continuous strip, so any
        # gap between pictures shows as a seam through the artwork.
        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._box.set_hexpand(True)
        viewport = Gtk.Viewport()
        viewport.set_child(self._box)
        self.set_child(viewport)
        self._page_widgets = []

        adj = self.get_vadjustment()
        adj.connect("value-changed", self._on_scroll_changed)
        self._on_end = None

    def set_on_end(self, cb):
        self._on_end = cb

    def _on_scroll_changed(self, adj):
        if not self._page_widgets:
            return
        if getattr(self, "_transitioning", False):
            return
            
        # Only trigger when practically at the very bottom
        if adj.get_value() + adj.get_page_size() >= adj.get_upper() - 5:
            if self._on_end:
                self._transitioning = True
                self._on_end()
                # reset guard after some time so we don't spam if they stay at bottom without loading next
                GLib.timeout_add(1000, lambda: setattr(self, "_transitioning", False) or False)

    def set_pages(self, pages, on_page_visible=None, content_fit=Gtk.ContentFit.FILL):
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
            pic.set_content_fit(content_fit)
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
        self._page_layout = "single"  # single | double | auto
        self._scale_type = "fit_page"  # fit_page | fit_width
        self._crop_borders = False
        self._tap_invert = False
        self._keep_screen_on = False
        self._fullscreen_enabled = False
        self._show_slider = True
        self._render_token = 0
        self._syncing_prefs = False
        self._ui_visible = True
        self._db = get_db()

        # Sliding-window prefetch, so a page turn is served from memory.
        self._page_cache = PageCache()
        image_loader.set_cache_limit(
            max(image_loader.DEFAULT_CACHE_LIMIT, self._page_cache.window_size * 4)
        )
        # Indices whose image turned out to be a landscape two-page spread.
        # Populated as pages decode, and used to keep double-page pairing
        # aligned the way Android does.
        self._spread_indices = set()
        # How far _next_page/_prev_page should step from the current view.
        self._page_step = 1
        # Chapter ids already reported to the trackers this session, so a
        # sync fires once per chapter rather than on every page turn past the
        # threshold.
        self._tracking_synced = set()

        self._build_ui()
        self._load_preferences()
        self._setup_keyboard()
        self.connect("map", self._on_mapped)

    def _build_ui(self):
        # The main container is an overlay
        self._main_overlay = Gtk.Overlay()
        self.append(self._main_overlay)
        self.set_vexpand(True)

        # ── Main Reader Area (Background layer) ────────────────────────────
        self._reader_stack = Gtk.Stack()
        self._reader_stack.set_vexpand(True)
        self._reader_stack.set_transition_type(Gtk.StackTransitionType.NONE)

        # Paged view
        self._paged_overlay = Gtk.Overlay()
        self._paged_overlay.add_css_class("reader-bg")

        self._page_stack = Gtk.Stack()
        self._page_stack.set_vexpand(True)
        self._page_stack.set_hexpand(True)
        self._page_stack.set_transition_type(Gtk.StackTransitionType.NONE)

        self._page_view = PageView()
        self._page_stack.add_named(self._page_view, "single")

        self._double_page_view = DoublePageView()
        self._page_stack.add_named(self._double_page_view, "double")

        self._paged_overlay.set_child(self._page_stack)

        # Loading spinner
        self._page_spinner = Gtk.Spinner()
        self._page_spinner.set_size_request(48, 48)
        self._page_spinner.set_halign(Gtk.Align.CENTER)
        self._page_spinner.set_valign(Gtk.Align.CENTER)
        self._page_spinner.add_css_class("reader-spinner")
        self._paged_overlay.add_overlay(self._page_spinner)

        # Tap zones (Left, Center, Right) for navigation
        tap_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        
        self._left_zone = Gtk.Button()
        self._left_zone.set_opacity(0)
        self._left_zone.set_hexpand(True)
        self._left_zone.connect("clicked", self._on_left_tap)
        tap_box.append(self._left_zone)

        self._center_zone = Gtk.Button()
        self._center_zone.set_opacity(0)
        self._center_zone.set_hexpand(True)
        self._center_zone.connect("clicked", self._toggle_ui)
        tap_box.append(self._center_zone)

        self._right_zone = Gtk.Button()
        self._right_zone.set_opacity(0)
        self._right_zone.set_hexpand(True)
        self._right_zone.connect("clicked", self._on_right_tap)
        tap_box.append(self._right_zone)

        self._paged_overlay.add_overlay(tap_box)
        self._reader_stack.add_named(self._paged_overlay, "paged")

        # Webtoon view
        # We also need a tap zone to toggle UI in webtoon mode
        self._webtoon_overlay = Gtk.Overlay()
        self._webtoon_view = WebtoonView()
        self._webtoon_view.set_on_end(self._on_chapter_finished)
        self._webtoon_overlay.set_child(self._webtoon_view)
        
        webtoon_center = Gtk.Button()
        webtoon_center.set_opacity(0)
        webtoon_center.set_hexpand(True)
        webtoon_center.set_vexpand(True)
        webtoon_center.connect("clicked", self._toggle_ui)
        
        # We don't want the button to block scroll completely, so we just use the overlay
        # Note: A full transparent button blocks mouse scrolling. For Tachiyomi style, 
        # a Gtk.GestureClick on the overlay is better, but since GTK doesn't easily let 
        # gestures pass through without stopping propagation unless configured carefully, 
        # we will add a thin strip or just rely on the HUD.
        self._webtoon_gesture = Gtk.GestureClick.new()
        self._webtoon_gesture.set_button(0) # any button
        self._webtoon_gesture.connect("pressed", lambda g, n, x, y: self._toggle_ui())
        self._webtoon_overlay.add_controller(self._webtoon_gesture)

        self._reader_stack.add_named(self._webtoon_overlay, "webtoon")
        
        # Set background to main overlay
        self._main_overlay.set_child(self._reader_stack)

        # ── HUD Overlays (Foreground layers) ───────────────────────────────

        # Top bar (auto-hide)
        self._top_bar = Adw.HeaderBar()
        self._top_bar.add_css_class("reader-header")
        self._top_bar.set_show_end_title_buttons(False)
        self._top_bar.set_show_start_title_buttons(False)
        self._top_bar.set_valign(Gtk.Align.START)

        back_btn = Gtk.Button(icon_name="go-previous-symbolic")
        back_btn.set_tooltip_text("Back to manga (Esc)")
        back_btn.connect("clicked", self._close)
        self._top_bar.pack_start(back_btn)

        self._chapter_title = Adw.WindowTitle()
        self._top_bar.set_title_widget(self._chapter_title)

        settings_btn = Gtk.MenuButton(icon_name="preferences-system-symbolic")
        settings_btn.set_tooltip_text("Reader settings")
        settings_btn.set_popover(self._build_settings_popover())
        self._top_bar.pack_end(settings_btn)

        self._main_overlay.add_overlay(self._top_bar)

        # Bottom HUD (Controls + Slider)
        self._bottom_hud = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._bottom_hud.set_valign(Gtk.Align.END)
        self._bottom_hud.add_css_class("reader-bottom-hud") # We will style this with a background

        # Controls row
        self._bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._bottom_bar.set_margin_start(16)
        self._bottom_bar.set_margin_end(16)
        self._bottom_bar.set_margin_top(8)

        prev_btn = Gtk.Button(icon_name="go-previous-symbolic")
        prev_btn.connect("clicked", lambda *_: self._prev_page())
        prev_btn.set_tooltip_text("Previous page (← or A)")
        self._bottom_bar.append(prev_btn)

        self._page_label = Gtk.Label(label="0 / 0")
        self._page_label.set_hexpand(True)
        self._page_label.set_justify(Gtk.Justification.CENTER)
        # Give it a background for visibility
        self._page_label.add_css_class("reader-page-indicator")
        self._bottom_bar.append(self._page_label)

        next_btn = Gtk.Button(icon_name="go-next-symbolic")
        next_btn.connect("clicked", lambda *_: self._next_page())
        next_btn.set_tooltip_text("Next page (→ or D)")
        self._bottom_bar.append(next_btn)

        self._bottom_hud.append(self._bottom_bar)

        # Page slider
        self._slider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._slider_box.set_margin_start(16)
        self._slider_box.set_margin_end(16)
        self._slider_box.set_margin_bottom(16)

        self._slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL)
        self._slider.set_hexpand(True)
        self._slider.set_draw_value(False)
        self._slider.set_range(0, 1)
        self._slider.connect("value-changed", self._on_slider_changed)
        self._slider_box.append(self._slider)
        self._slider_changing = False

        self._bottom_hud.append(self._slider_box)

        self._main_overlay.add_overlay(self._bottom_hud)

    def _toggle_ui(self, *_):
        self._ui_visible = not self._ui_visible
        self._top_bar.set_visible(self._ui_visible)
        self._bottom_hud.set_visible(self._ui_visible)

    def _build_settings_popover(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_size_request(320, -1)

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

        # Page layout
        layout_label = Gtk.Label(label="Page Layout")
        layout_label.add_css_class("heading")
        layout_label.set_halign(Gtk.Align.START)
        box.append(layout_label)

        layout_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        layout_box.add_css_class("linked")

        self._single_layout_btn = Gtk.ToggleButton(label="Single")
        self._single_layout_btn.set_active(True)
        self._single_layout_btn.set_hexpand(True)
        self._single_layout_btn.connect("toggled", self._set_page_layout, "single")
        layout_box.append(self._single_layout_btn)

        self._double_layout_btn = Gtk.ToggleButton(label="Double")
        self._double_layout_btn.set_group(self._single_layout_btn)
        self._double_layout_btn.set_hexpand(True)
        self._double_layout_btn.connect("toggled", self._set_page_layout, "double")
        layout_box.append(self._double_layout_btn)

        self._auto_layout_btn = Gtk.ToggleButton(label="Auto")
        self._auto_layout_btn.set_group(self._single_layout_btn)
        self._auto_layout_btn.set_hexpand(True)
        self._auto_layout_btn.set_tooltip_text(
            f"Double pages when the window is at least {AUTO_DOUBLE_MIN_WIDTH}px wide"
        )
        self._auto_layout_btn.connect("toggled", self._set_page_layout, "auto")
        layout_box.append(self._auto_layout_btn)

        box.append(layout_box)

        # Scale type
        scale_label = Gtk.Label(label="Scale Type")
        scale_label.add_css_class("heading")
        scale_label.set_halign(Gtk.Align.START)
        box.append(scale_label)

        scale_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        scale_box.add_css_class("linked")

        self._fit_page_btn = Gtk.ToggleButton(label="Fit Page")
        self._fit_page_btn.set_active(True)
        self._fit_page_btn.set_hexpand(True)
        self._fit_page_btn.connect("toggled", self._set_scale_type, "fit_page")
        scale_box.append(self._fit_page_btn)

        self._fit_width_btn = Gtk.ToggleButton(label="Fit Width")
        self._fit_width_btn.set_group(self._fit_page_btn)
        self._fit_width_btn.set_hexpand(True)
        self._fit_width_btn.connect("toggled", self._set_scale_type, "fit_width")
        scale_box.append(self._fit_width_btn)

        box.append(scale_box)

        # Reader behavior toggles
        self._crop_toggle = Gtk.CheckButton(label="Crop Borders")
        self._crop_toggle.connect("toggled", self._set_crop_borders)
        box.append(self._crop_toggle)

        self._tap_invert_toggle = Gtk.CheckButton(label="Invert Tap Zones")
        self._tap_invert_toggle.connect("toggled", self._set_tap_invert)
        box.append(self._tap_invert_toggle)

        self._slider_toggle = Gtk.CheckButton(label="Show Page Slider")
        self._slider_toggle.set_active(True)
        self._slider_toggle.connect("toggled", self._set_show_slider)
        box.append(self._slider_toggle)

        self._fullscreen_toggle = Gtk.CheckButton(label="Fullscreen Reader")
        self._fullscreen_toggle.connect("toggled", self._set_fullscreen_mode)
        box.append(self._fullscreen_toggle)

        self._keep_screen_on_toggle = Gtk.CheckButton(label="Keep Screen On")
        self._keep_screen_on_toggle.connect("toggled", self._set_keep_screen_on)
        box.append(self._keep_screen_on_toggle)

        # Background color
        bg_label = Gtk.Label(label="Background")
        bg_label.add_css_class("heading")
        bg_label.set_halign(Gtk.Align.START)
        box.append(bg_label)

        bg_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bg_box.add_css_class("linked")

        self._black_bg_btn = Gtk.ToggleButton(label="Black")
        self._black_bg_btn.set_active(True)
        self._black_bg_btn.set_hexpand(True)
        self._black_bg_btn.connect("toggled", self._set_bg, "black")
        bg_box.append(self._black_bg_btn)

        self._white_bg_btn = Gtk.ToggleButton(label="White")
        self._white_bg_btn.set_group(self._black_bg_btn)
        self._white_bg_btn.set_hexpand(True)
        self._white_bg_btn.connect("toggled", self._set_bg, "white")
        bg_box.append(self._white_bg_btn)

        self._gray_bg_btn = Gtk.ToggleButton(label="Gray")
        self._gray_bg_btn.set_group(self._black_bg_btn)
        self._gray_bg_btn.set_hexpand(True)
        self._gray_bg_btn.connect("toggled", self._set_bg, "gray")
        bg_box.append(self._gray_bg_btn)

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

    # ── Preferences ───────────────────────────────────────────────────────

    def _load_preferences(self):
        direction_raw = self._db.get_setting("reading_direction", ReadingDirection.RTL.value)
        try:
            self._direction = ReadingDirection(direction_raw)
        except Exception:
            self._direction = ReadingDirection.RTL

        self._page_layout = self._db.get_setting("page_layout", "single")
        if self._page_layout not in ("single", "double", "auto"):
            self._page_layout = "single"

        self._scale_type = self._db.get_setting("scale_type", "fit_page")
        if self._scale_type not in ("fit_page", "fit_width"):
            self._scale_type = "fit_page"

        self._crop_borders = self._db.get_setting("crop_borders", "0") == "1"
        self._tap_invert = self._db.get_setting("reader_tap_invert", "0") == "1"
        self._fullscreen_enabled = self._db.get_setting("reader_fullscreen", "0") == "1"
        self._keep_screen_on = self._db.get_setting("reader_keep_screen_on", "0") == "1"
        self._show_slider = self._db.get_setting("reader_show_slider", "1") == "1"
        try:
            self._zoom = float(self._db.get_setting("reader_zoom", "1.0"))
        except Exception:
            self._zoom = 1.0

        bg = self._db.get_setting("reader_background", "black")
        if bg not in ("black", "white", "gray"):
            bg = "black"
        self._reader_bg = bg
        self._sync_settings_controls()
        self._apply_reader_preferences()

    def _sync_settings_controls(self):
        self._syncing_prefs = True
        if hasattr(self, "_rtl_btn"):
            self._rtl_btn.set_active(self._direction == ReadingDirection.RTL)
            self._ltr_btn.set_active(self._direction == ReadingDirection.LTR)
            self._webtoon_btn.set_active(self._direction == ReadingDirection.WEBTOON)

        if hasattr(self, "_single_layout_btn"):
            self._single_layout_btn.set_active(self._page_layout == "single")
            self._double_layout_btn.set_active(self._page_layout == "double")
            self._auto_layout_btn.set_active(self._page_layout == "auto")

        if hasattr(self, "_fit_page_btn"):
            self._fit_page_btn.set_active(self._scale_type == "fit_page")
            self._fit_width_btn.set_active(self._scale_type == "fit_width")

        if hasattr(self, "_black_bg_btn"):
            self._black_bg_btn.set_active(self._reader_bg == "black")
            self._white_bg_btn.set_active(self._reader_bg == "white")
            self._gray_bg_btn.set_active(self._reader_bg == "gray")

        if hasattr(self, "_crop_toggle"):
            self._crop_toggle.set_active(self._crop_borders)
        if hasattr(self, "_tap_invert_toggle"):
            self._tap_invert_toggle.set_active(self._tap_invert)
        if hasattr(self, "_slider_toggle"):
            self._slider_toggle.set_active(self._show_slider)
        if hasattr(self, "_fullscreen_toggle"):
            self._fullscreen_toggle.set_active(self._fullscreen_enabled)
        if hasattr(self, "_keep_screen_on_toggle"):
            self._keep_screen_on_toggle.set_active(self._keep_screen_on)

        if hasattr(self, "_zoom_label"):
            self._zoom_label.set_text(f"{int(self._zoom * 100)}%")
        self._syncing_prefs = False

    def _persist_reader_setting(self, key: str, value: str):
        self._db.set_setting(key, value)

    def _apply_reader_preferences(self):
        # Mode + direction
        if self._direction == ReadingDirection.WEBTOON:
            self._mode = "webtoon"
            self._reader_stack.set_visible_child_name("webtoon")
            self._bottom_bar.set_visible(False)
        else:
            self._mode = "paged"
            self._reader_stack.set_visible_child_name("paged")
            self._bottom_bar.set_visible(True)

        self._apply_page_layout()
        self._apply_scale_and_crop()
        self._apply_background_color(self._reader_bg)
        self._apply_fullscreen()
        self._apply_slider_visibility()

    def _effective_layout(self) -> str:
        """
        Resolve the layout preference to what is actually drawn.

        "auto" means double-page on a window wide enough to fit two pages
        side by side, and single-page otherwise. There is no phone-sized
        equivalent on Android; this exists because a desktop window changes
        width while reading.
        """
        if self._page_layout != "auto":
            return self._page_layout
        return "double" if should_auto_double(self._window_width()) else "single"

    def _window_width(self) -> int:
        width = self.get_width()
        if width > 0:
            return width
        root = self.get_root()
        return root.get_width() if root is not None else 0

    def _on_mapped(self, *_):
        """
        Start watching the window for width changes.

        Gtk.Widget has no width property to notify on, so watch the toplevel
        window's own size properties instead. They only change on a real
        resize, unlike a per-frame tick callback.
        """
        root = self.get_root()
        if root is None or getattr(self, "_resize_watch_root", None) is root:
            return
        self._resize_watch_root = root
        for prop in ("default-width", "maximized", "fullscreened"):
            try:
                root.connect(f"notify::{prop}", self._on_reader_resized)
            except TypeError:
                # Not every toplevel exposes all three.
                pass
        self._on_reader_resized()

    def _on_reader_resized(self, *_):
        """Re-render when an "auto" layout crosses the double-page threshold."""
        if self._page_layout != "auto" or not self._pages:
            return
        resolved = self._effective_layout()
        if resolved == getattr(self, "_last_resolved_layout", None):
            return
        self._last_resolved_layout = resolved
        self._apply_page_layout()
        if self._mode == "paged":
            self._show_page(self._current_page)

    def _apply_page_layout(self):
        self._last_resolved_layout = self._effective_layout()
        if self._effective_layout() == "double":
            self._page_stack.set_visible_child_name("double")
        else:
            self._page_stack.set_visible_child_name("single")

    def _apply_scale_and_crop(self):
        if self._crop_borders:
            fit = Gtk.ContentFit.COVER
        else:
            fit = Gtk.ContentFit.CONTAIN if self._scale_type == "fit_page" else Gtk.ContentFit.FILL
        self._page_view.set_content_fit(fit)
        self._double_page_view.set_content_fit(fit)

    def _apply_background_color(self, color: str):
        css_map = {
            "black": "background-color: #000;",
            "white": "background-color: #fff;",
            "gray": "background-color: #333;",
        }
        provider = Gtk.CssProvider()
        provider.load_from_string(f".reader-bg {{ {css_map.get(color, '')} }}")
        display = self.get_display()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )

    def _apply_fullscreen(self):
        root = self.get_root()
        if isinstance(root, Gtk.Window):
            try:
                if self._fullscreen_enabled:
                    root.fullscreen()
                else:
                    root.unfullscreen()
            except Exception:
                pass

    def _apply_slider_visibility(self):
        self._slider_box.set_visible(self._show_slider and self._mode == "paged")

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

    def load_chapter(self, manga: Manga, chapter: Chapter, force_start: bool = False):
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
                    from pathlib import Path
                    path = Path(chapter.local_path)
                    if path.exists():
                        image_exts = (".jpg", ".jpeg", ".png", ".webp", ".avif")
                        files = []
                        if path.is_file():
                            if path.suffix.lower() in image_exts:
                                files = [path]
                        else:
                            files = sorted(
                                f for f in path.rglob("*")
                                if f.is_file() and f.suffix.lower() in image_exts
                            )

                        expected = chapter.page_count or 0
                        is_complete_local = expected <= 0 or len(files) >= expected
                        if files and is_complete_local:
                            pages = []
                            for i, f in enumerate(files):
                                p = Page(index=i, url=str(f), image_url=str(f), local_path=str(f))
                                pages.append(p)
                            GLib.idle_add(self._on_pages_loaded, pages, force_start)
                            return
                        # Local directory exists but is empty/partial; fall back to source.

                pages = ext.get_pages(chapter)
                GLib.idle_add(self._on_pages_loaded, pages, force_start)
            except Exception as e:
                GLib.idle_add(self._on_load_error, str(e))

        threading.Thread(target=fetch, daemon=True).start()

    def _on_pages_loaded(self, pages, force_start=False):
        self._pages = pages
        self._spread_indices = set()
        self._page_cache.set_pages(pages)
        self._page_spinner.stop()
        self._page_spinner.set_visible(False)

        if not pages:
            self._page_label.set_text("No pages found")
            return

        # Restore last page or start from beginning
        if force_start:
            self._current_page = 0
            # Automatically save progress to reset it in the database as well
            if self._chapter and self._chapter.id:
                self._db.update_chapter_progress(self._chapter.id, 0)
        elif self._chapter.last_page_read > 0:
            self._current_page = min(self._chapter.last_page_read, len(pages) - 1)
        else:
            self._current_page = 0

        # Setup slider
        self._slider.set_range(0, max(len(pages) - 1, 1))
        step = 2 if self._mode == "paged" and self._effective_layout() == "double" else 1
        self._slider.set_increments(step, step)

        if self._mode == "webtoon":
            self._webtoon_view.set_pages(pages, content_fit=Gtk.ContentFit.FILL)
            self._reader_stack.set_visible_child_name("webtoon")
        else:
            self._reader_stack.set_visible_child_name("paged")
            self._apply_page_layout()
            self._show_page(self._current_page)

    def _on_load_error(self, message):
        self._page_spinner.stop()
        self._page_spinner.set_visible(False)
        self._page_label.set_text(f"Error: {message}")
        logger.error("chapter load failed: %s", message)
        if self._manga is not None and self._chapter is not None:
            notify_retry(
                self,
                f"Could not load this chapter: {message}",
                lambda: self.load_chapter(self._manga, self._chapter),
            )

    # ── Double-page pairing ───────────────────────────────────────────────

    def _page_pairs(self):
        """
        Group pages into what each double-page view shows.

        A landscape image is a two-page spread scanned as one file, so it
        takes the viewport alone and everything after it shifts by one. Pages
        whose size is not known yet are assumed narrow, which is what a fixed
        even/odd pairing would have done anyway.
        """
        pairs = []
        i = 0
        total = len(self._pages)
        while i < total:
            if i in self._spread_indices:
                pairs.append((i, i + 1))
                i += 1
            elif i + 1 < total and (i + 1) in self._spread_indices:
                # The next page is a spread, so this one stands alone rather
                # than being paired with half of a spread.
                pairs.append((i, i + 1))
                i += 1
            else:
                pairs.append((i, min(i + 2, total)))
                i += 2
        return pairs

    def _pair_containing(self, idx):
        """The (start, end) pair covering ``idx``, end exclusive."""
        for pair in self._page_pairs():
            if pair[0] <= idx < pair[1]:
                return pair
        return (idx, min(idx + 1, len(self._pages)))

    def _mark_spread(self, idx, pixbuf) -> bool:
        """Record a decoded page as a spread. True when that is new."""
        if not pixbuf_is_spread(pixbuf) or idx in self._spread_indices:
            return False
        self._spread_indices.add(idx)
        return True

    def _show_page(self, idx):
        if not self._pages or idx < 0 or idx >= len(self._pages):
            return

        is_double = self._mode == "paged" and self._effective_layout() == "double"

        if is_double:
            idx, pair_end = self._pair_containing(idx)
            self._page_step = pair_end - idx
        else:
            pair_end = idx + 1
            self._page_step = 1

        self._current_page = idx
        self._render_token += 1
        token = self._render_token

        if is_double and pair_end - idx > 1:
            self._page_label.set_text(f"{idx + 1}-{pair_end} / {len(self._pages)}")
        else:
            self._page_label.set_text(f"{idx + 1} / {len(self._pages)}")

        # Update slider without triggering callback
        self._slider_changing = True
        self._slider.set_value(idx)
        self._slider_changing = False

        # Warm the pages around this one so the next turn is already decoded.
        self._page_cache.focus(idx)

        # Save progress
        progress_idx = pair_end - 1 if is_double else idx
        self._save_progress(progress_idx)

        if is_double:
            left_page = self._pages[idx]
            right_page = self._pages[idx + 1] if pair_end - idx > 1 else None
            self._double_page_view.set_loading()

            def set_left(pb):
                if token != self._render_token:
                    return
                if self._mark_spread(idx, pb):
                    # This page turned out to be a full spread. Re-render so it
                    # gets the whole viewport and the pairing after it shifts.
                    self._show_page(idx)
                    return
                self._double_left_pb = pb
                if right_page is None:
                    self._double_page_view.set_spread(pb)
                else:
                    self._double_page_view.set_pixbufs(
                        pb, getattr(self, "_double_right_pb", None)
                    )

            def set_right(pb):
                if token != self._render_token:
                    return
                if self._mark_spread(idx + 1, pb):
                    # The right half is a spread, so it cannot share this view.
                    self._show_page(idx)
                    return
                self._double_right_pb = pb
                self._double_page_view.set_pixbufs(
                    getattr(self, "_double_left_pb", None), pb
                )

            self._double_left_pb = None
            self._double_right_pb = None
            self._load_page_pixbuf(left_page, set_left)
            if right_page is not None:
                self._load_page_pixbuf(right_page, set_right)
            return

        # Single-page load
        page = self._pages[idx]
        self._page_view.set_loading()

        def set_single(pb):
            if token != self._render_token:
                return
            self._page_view.set_pixbuf(pb)

        self._load_page_pixbuf(page, set_single)

    def _load_page_pixbuf(self, page: Page, on_ready):
        if page.local_path:
            pixbuf = image_loader.load_local_image(page.local_path)
            on_ready(pixbuf)
        else:
            primary_url = page.image_url or page.url
            fallback_url = page.url if page.url and page.url != primary_url else ""

            def on_primary_ready(pb):
                if pb is not None or not fallback_url:
                    on_ready(pb)
                    return
                image_loader.load_image_async(fallback_url, on_ready)

            image_loader.load_image_async(primary_url, on_primary_ready)

    def _next_page(self):
        # Step by what the current view actually covers: two pages normally,
        # one when a spread is on screen.
        step = self._page_step if self._mode == "paged" else 1
        if self._current_page + step < len(self._pages):
            self._show_page(self._current_page + step)
        elif self._current_page < len(self._pages) - 1:
            self._show_page(len(self._pages) - 1)
        else:
            self._on_chapter_finished()

    def _prev_page(self):
        if self._current_page <= 0:
            return
        if self._mode == "paged" and self._effective_layout() == "double":
            # Land on the start of the previous pair, not a fixed two back.
            previous = None
            for pair_start, pair_end in self._page_pairs():
                if pair_end > self._current_page:
                    break
                previous = pair_start
            self._show_page(previous if previous is not None else 0)
            return
        self._show_page(self._current_page - 1)

    def _on_left_tap(self, *_):
        rtl = self._direction == ReadingDirection.RTL
        if self._tap_invert:
            rtl = not rtl
        if rtl:
            self._next_page()
        else:
            self._prev_page()

    def _on_right_tap(self, *_):
        rtl = self._direction == ReadingDirection.RTL
        if self._tap_invert:
            rtl = not rtl
        if rtl:
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
            if not getattr(self._chapter, 'read', False):
                self._db.mark_chapter_read(self._chapter.id, len(self._pages) - 1)
                self._chapter.read = True
            
            self._go_to_next_chapter()

    def _go_to_next_chapter(self):
        if getattr(self, "_transitioning_chapter", False):
            return
        self._transitioning_chapter = True

        if not self._manga or not self._manga.id:
            self._transitioning_chapter = False
            return
        
        chapters = self._db.get_chapters(self._manga.id)
        # Sort ascending by chapter_number
        chapters = sorted(chapters, key=lambda c: c.chapter_number)
        
        next_ch = None
        for ch in chapters:
            if ch.chapter_number > self._chapter.chapter_number:
                next_ch = ch
                break
                
        if not next_ch:
            self._transitioning_chapter = False
            return
            
        # Load the next chapter seamlessly, forcing start from beginning
        self.load_chapter(self._manga, next_ch, force_start=True)
        # Reset flag after some time so that we don't block subsequent transitions
        GLib.timeout_add(1000, lambda: setattr(self, "_transitioning_chapter", False) or False)

    def _save_progress(self, page_idx: int):
        if self._chapter and self._chapter.id and self._manga and self._manga.id:
            self._db.update_chapter_progress(self._chapter.id, page_idx)
            self._db.record_history(self._manga.id, self._chapter.id, page_idx)
            self._maybe_sync_tracking(page_idx)

    def _maybe_sync_tracking(self, page_idx: int):
        """
        Push this chapter to the linked trackers once it is read far enough.

        Android fires at roughly 85% of the last page rather than on the page
        turn, so a chapter opened by accident does not register. The sync runs
        once per chapter and on a worker thread, since it makes network calls.
        """
        chapter = self._chapter
        if chapter is None or self._manga is None or self._manga.id is None:
            return
        if chapter.id in self._tracking_synced:
            return
        if not TrackManager.should_sync(page_idx, len(self._pages)):
            return

        chapter_number = chapter.chapter_number
        if chapter_number is None or chapter_number < 0:
            return

        self._tracking_synced.add(chapter.id)
        manga_id = self._manga.id

        def work():
            try:
                manager = get_track_manager()
                if not manager.entries_for(manga_id):
                    return
                manager.sync_progress(manga_id, chapter_number)
                manager.process_queue()
            except Exception as exc:
                logger.warning("tracker sync failed: %s", exc)

        threading.Thread(target=work, daemon=True).start()

    def _set_direction(self, btn, direction: ReadingDirection):
        if self._syncing_prefs or not btn.get_active():
            return
        self._direction = direction
        self._persist_reader_setting("reading_direction", direction.value)
        if direction == ReadingDirection.WEBTOON:
            self._mode = "webtoon"
            if self._pages:
                self._webtoon_view.set_pages(self._pages, content_fit=Gtk.ContentFit.FILL)
            self._reader_stack.set_visible_child_name("webtoon")
            self._bottom_bar.set_visible(False)
            self._apply_slider_visibility()
        else:
            self._mode = "paged"
            self._reader_stack.set_visible_child_name("paged")
            self._bottom_bar.set_visible(True)
            self._apply_slider_visibility()
            self._apply_page_layout()
            if self._pages:
                self._show_page(self._current_page)
        self._apply_fullscreen()

    def _set_page_layout(self, btn, layout: str):
        if self._syncing_prefs or not btn.get_active():
            return
        self._page_layout = layout
        self._persist_reader_setting("page_layout", layout)
        self._apply_page_layout()
        if self._pages and self._mode == "paged":
            self._show_page(self._current_page)

    def _set_scale_type(self, btn, scale_type: str):
        if self._syncing_prefs or not btn.get_active():
            return
        self._scale_type = scale_type
        self._persist_reader_setting("scale_type", scale_type)
        self._apply_scale_and_crop()
        if self._pages and self._mode == "paged":
            self._show_page(self._current_page)

    def _set_crop_borders(self, btn):
        if self._syncing_prefs:
            return
        self._crop_borders = btn.get_active()
        self._persist_reader_setting("crop_borders", "1" if self._crop_borders else "0")
        self._apply_scale_and_crop()
        if self._pages and self._mode == "paged":
            self._show_page(self._current_page)

    def _set_tap_invert(self, btn):
        if self._syncing_prefs:
            return
        self._tap_invert = btn.get_active()
        self._persist_reader_setting("reader_tap_invert", "1" if self._tap_invert else "0")

    def _set_show_slider(self, btn):
        if self._syncing_prefs:
            return
        self._show_slider = btn.get_active()
        self._persist_reader_setting("reader_show_slider", "1" if self._show_slider else "0")
        self._apply_slider_visibility()

    def _set_fullscreen_mode(self, btn):
        if self._syncing_prefs:
            return
        self._fullscreen_enabled = btn.get_active()
        self._persist_reader_setting("reader_fullscreen", "1" if self._fullscreen_enabled else "0")
        self._apply_fullscreen()

    def _set_keep_screen_on(self, btn):
        if self._syncing_prefs:
            return
        self._keep_screen_on = btn.get_active()
        self._persist_reader_setting("reader_keep_screen_on", "1" if self._keep_screen_on else "0")

    def _set_bg(self, btn, color):
        if self._syncing_prefs or not btn.get_active():
            return
        self._reader_bg = color
        self._persist_reader_setting("reader_background", color)
        self._apply_background_color(color)

    def _set_zoom(self, zoom):
        self._zoom = max(0.3, min(3.0, zoom))
        self._zoom_label.set_text(f"{int(self._zoom * 100)}%")
        self._persist_reader_setting("reader_zoom", f"{self._zoom:.2f}")
        # Zoom is handled by page widget resize
        if self._pages:
            self._show_page(self._current_page)

    def _close(self, *_):
        # Drop the prefetch window so a closed chapter stops holding memory.
        self._page_cache.clear()
        root = self.get_root()
        if isinstance(root, Gtk.Window):
            try:
                root.unfullscreen()
            except Exception:
                pass
        if self._on_close:
            self._on_close()
