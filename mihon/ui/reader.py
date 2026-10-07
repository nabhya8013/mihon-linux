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
from ..core import image_loader, reader_logic
from ..core.privacy import is_incognito
from ..core.page_cache import (
    AUTO_DOUBLE_MIN_WIDTH,
    PageCache,
    pixbuf_is_spread,
    should_auto_double,
)
from ..extensions.registry import get_registry
from ..core.tracking import TrackManager, get_track_manager
from .notify import notify, notify_retry
import logging

logger = logging.getLogger("reader")


class SizedPicture(Gtk.Picture):
    """
    A picture that measures exactly the size it is told to.

    Gtk.Picture reports the image's own pixel size as its natural size, which
    is what made fit-width squash the page and zoom do nothing. The reader
    works the display size out itself (``reader_logic.fit_sizes``) and hands
    it here; until then the picture asks for no space at all.
    """

    def __init__(self):
        super().__init__()
        self._target = (0, 0)
        self.set_can_shrink(True)
        self.set_content_fit(Gtk.ContentFit.FILL)

    def set_target_size(self, width: int, height: int):
        size = (max(0, int(width)), max(0, int(height)))
        if size != self._target:
            self._target = size
            self.queue_resize()

    @property
    def target_size(self):
        return self._target

    def do_measure(self, orientation, for_size):
        value = self._target[0] if orientation == Gtk.Orientation.HORIZONTAL else self._target[1]
        return value, value, -1, -1


def _image_size(pixbuf):
    return (pixbuf.get_width(), pixbuf.get_height()) if pixbuf is not None else (0, 0)


class _FitScroller(Gtk.ScrolledWindow):
    """
    A scrolled window that re-fits its pages whenever its viewport resizes.

    The viewport size is read off the adjustments' page size, which GTK
    updates on every allocation, so there is no polling and no dependence on
    which window property happened to change.
    """

    def __init__(self):
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._scale_type = "fit_page"
        self._crop = False
        self._zoom = 1.0
        self._last_view = (0, 0)
        self._relayout_queued = False
        for adj in (self.get_hadjustment(), self.get_vadjustment()):
            adj.connect("changed", self._on_viewport_changed)

    def configure(self, scale_type: str, crop: bool, zoom: float):
        self._scale_type = scale_type
        self._crop = crop
        self._zoom = reader_logic.clamp_zoom(zoom)
        self._relayout()

    def set_content_fit(self, fit):
        # Kept for callers that still pass a ContentFit; sizing is done in
        # configure() now, so only crop (COVER) needs remembering.
        self._crop = fit == Gtk.ContentFit.COVER
        self._relayout()

    def _view_size(self):
        return (
            int(self.get_hadjustment().get_page_size()) or self.get_width(),
            int(self.get_vadjustment().get_page_size()) or self.get_height(),
        )

    def _on_viewport_changed(self, *_):
        if self._view_size() == self._last_view or self._relayout_queued:
            return
        # Resizing a child from inside the allocation that reported the new
        # size would recurse; do it once the allocation has finished.
        self._relayout_queued = True

        def run():
            self._relayout_queued = False
            self._relayout()
            return False

        GLib.idle_add(run)

    def _scroll_to_start(self):
        self.get_vadjustment().set_value(0)
        self.get_hadjustment().set_value(0)

    def _relayout(self):
        raise NotImplementedError


class PageView(_FitScroller):
    """Single page display widget."""

    def __init__(self):
        super().__init__()
        self._pixbuf = None
        self._picture = SizedPicture()
        self._picture.set_halign(Gtk.Align.CENTER)
        self._picture.set_valign(Gtk.Align.CENTER)
        self._picture.add_css_class("reader-page")
        self.set_child(self._picture)

    def set_pixbuf(self, pixbuf):
        self._pixbuf = pixbuf
        self._picture.set_pixbuf(pixbuf)
        self._relayout()
        self._scroll_to_start()

    def set_loading(self):
        self.set_pixbuf(None)

    def _relayout(self):
        vw, vh = self._last_view = self._view_size()
        if self._pixbuf is None or vw <= 0 or vh <= 0:
            self._picture.set_target_size(0, 0)
            return
        if self._crop:
            z = reader_logic.clamp_zoom(self._zoom)
            self._picture.set_content_fit(Gtk.ContentFit.COVER)
            self._picture.set_target_size(vw * z, vh * z)
            return
        self._picture.set_content_fit(Gtk.ContentFit.FILL)
        (w, h), = reader_logic.fit_sizes(
            [_image_size(self._pixbuf)], vw, vh, self._scale_type, self._zoom
        )
        self._picture.set_target_size(w, h)


class DoublePageView(_FitScroller):
    """Two-page spread display for paged mode."""

    SPACING = 4

    def __init__(self):
        super().__init__()
        self._box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=self.SPACING)
        self._box.set_halign(Gtk.Align.CENTER)
        self._box.set_valign(Gtk.Align.CENTER)
        self.set_child(self._box)

        self._left = SizedPicture()
        self._right = SizedPicture()
        for pic in (self._left, self._right):
            pic.add_css_class("reader-page")
            self._box.append(pic)
        self._pixbufs = (None, None)
        self._spread = False

    def set_pixbufs(self, left, right):
        self._spread = False
        self._pixbufs = (left, right)
        self._left.set_pixbuf(left if left else None)
        self._right.set_pixbuf(right if right else None)
        self._right.set_visible(right is not None)
        self._relayout()
        self._scroll_to_start()

    def set_spread(self, pixbuf):
        """Show one landscape image across the whole viewport, unpaired."""
        self._spread = True
        self._pixbufs = (pixbuf, None)
        self._left.set_pixbuf(pixbuf if pixbuf else None)
        self._right.set_pixbuf(None)
        self._right.set_visible(False)
        self._relayout()
        self._scroll_to_start()

    def set_loading(self):
        self._pixbufs = (None, None)
        self._left.set_pixbuf(None)
        self._right.set_pixbuf(None)
        self._relayout()

    def _relayout(self):
        vw, vh = self._last_view = self._view_size()
        left, right = self._pixbufs
        shown = [pb for pb in (left, right) if pb is not None]
        if not shown or vw <= 0 or vh <= 0:
            self._left.set_target_size(0, 0)
            self._right.set_target_size(0, 0)
            return
        pictures = [self._left] if right is None else [self._left, self._right]
        z = reader_logic.clamp_zoom(self._zoom)
        if self._crop:
            each_w = (vw - self.SPACING * (len(pictures) - 1)) / len(pictures)
            for pic in pictures:
                pic.set_content_fit(Gtk.ContentFit.COVER)
                pic.set_target_size(each_w * z, vh * z)
            return
        sizes = reader_logic.fit_sizes(
            [_image_size(left), _image_size(right)][: len(pictures)],
            vw, vh, self._scale_type, self._zoom, spacing=self.SPACING,
        )
        for pic, (w, h) in zip(pictures, sizes):
            pic.set_content_fit(Gtk.ContentFit.FILL)
            pic.set_target_size(w, h)


class WebtoonView(Gtk.ScrolledWindow):
    """
    Continuous vertical scroll view for webtoons.

    Every strip gets an explicit height from its own aspect ratio, so strips
    meet with no gap and no stretching. Only a window of strips around the
    one being read holds an image; the rest keep their height but drop the
    pixels, which bounds memory on long chapters. Because every height is
    known, the strip on screen is worked out from the scroll offset rather
    than from widget allocations.
    """

    BEHIND = 2
    AHEAD = 4

    def __init__(self):
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # No spacing: webtoon panels are cut from one continuous strip, so any
        # gap between pictures shows as a seam through the artwork.
        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._box.set_halign(Gtk.Align.CENTER)
        self.set_child(self._box)

        self._pages = []
        self._pictures = []
        self._image_sizes = []   # (w, h) per strip once decoded, else (0, 0)
        self._heights = []
        self._loaded = set()
        self._loader = None
        self._on_page_visible = None
        self._on_end = None
        self._zoom = 1.0
        self._padding = 0
        self._width = 0
        self._current = 0
        self._generation = 0
        self._anchor = None      # (index, fraction into that strip) to hold on screen
        self._transitioning = False

        vadj = self.get_vadjustment()
        vadj.connect("value-changed", self._on_scroll_changed)
        vadj.connect("changed", self._on_layout_changed)
        self.get_hadjustment().connect("changed", self._on_layout_changed)

    # ── Public API ────────────────────────────────────────────────────────

    def set_on_end(self, cb):
        self._on_end = cb

    def set_zoom(self, zoom: float):
        self._zoom = reader_logic.clamp_zoom(zoom)
        self._resize_strips()

    def set_padding(self, percent: int):
        self._padding = percent
        self._resize_strips()

    def _target_width(self) -> int:
        return reader_logic.webtoon_strip_width(self._view_width(), self._zoom, self._padding)

    def set_pages(self, pages, on_page_visible=None, loader=None, start_index=0, **_ignored):
        self._generation += 1
        child = self._box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._box.remove(child)
            child = nxt

        self._pages = list(pages)
        self._loader = loader
        self._on_page_visible = on_page_visible
        self._pictures = []
        self._image_sizes = [(0, 0)] * len(self._pages)
        self._heights = [0] * len(self._pages)
        self._loaded = set()
        self._current = max(0, min(start_index, len(self._pages) - 1)) if self._pages else 0
        self._transitioning = False

        for _ in self._pages:
            pic = SizedPicture()
            pic.add_css_class("reader-page")
            self._box.append(pic)
            self._pictures.append(pic)

        self._width = 0
        self._resize_strips()
        self.scroll_to_page(self._current)
        self._update_window()

    def scroll_to_page(self, page_idx):
        if not (0 <= page_idx < len(self._pictures)):
            return
        self._anchor = (page_idx, 0.0)
        self._apply_anchor()

    @property
    def current_page(self) -> int:
        return self._current

    # ── Layout ────────────────────────────────────────────────────────────

    def _view_width(self) -> int:
        return int(self.get_hadjustment().get_page_size()) or self.get_width()

    def _tops(self):
        tops, y = [], 0
        for h in self._heights:
            tops.append(y)
            y += h
        return tops

    def _capture_anchor(self):
        if not self._heights:
            return None
        value = self.get_vadjustment().get_value()
        tops = self._tops()
        idx = reader_logic.page_at_offset(tops, value)
        height = self._heights[idx] or 1
        return idx, (value - tops[idx]) / height

    def _apply_anchor(self):
        # Before the first allocation the width is 0, every height is 0 and
        # every target is 0. Applying it then would "succeed" at the top and
        # drop the anchor, so wait until the strips have real sizes.
        if self._anchor is None or not self._heights or self._width <= 0:
            return
        idx, fraction = self._anchor
        target = self._tops()[idx] + fraction * self._heights[idx]
        adj = self.get_vadjustment()
        # Until GTK has laid out the new heights the adjustment's upper bound
        # is stale and set_value() would clamp; keep the anchor and retry on
        # the next "changed".
        if target <= adj.get_upper() - adj.get_page_size() + 1 or target == 0:
            adj.set_value(target)
            self._anchor = None

    def _set_height(self, idx, height):
        if self._heights[idx] == height:
            return
        if self._anchor is None and idx < self._current:
            # A strip above the reader changed size; hold the reader's place.
            self._anchor = self._capture_anchor()
        self._heights[idx] = height
        self._pictures[idx].set_target_size(self._width, height)
        self._apply_anchor()

    def _resize_strips(self):
        width = self._target_width()
        if width == self._width or not self._pictures:
            self._width = width
            return
        if self._anchor is None and self._width:
            self._anchor = self._capture_anchor()
        self._width = width
        for idx, (w, h) in enumerate(self._image_sizes):
            self._heights[idx] = reader_logic.strip_height(w, h, width)
            self._pictures[idx].set_target_size(width, self._heights[idx])
        self._apply_anchor()

    def _on_layout_changed(self, *_):
        if self._view_width() and self._target_width() != self._width:
            GLib.idle_add(lambda: self._resize_strips() or False)
        self._apply_anchor()

    # ── Loading window ────────────────────────────────────────────────────

    def _update_window(self):
        wanted = set(reader_logic.window_range(self._current, len(self._pages), self.BEHIND, self.AHEAD))
        for idx in self._loaded - wanted:
            # Keep the height, drop the pixels.
            self._pictures[idx].set_pixbuf(None)
        self._loaded &= wanted
        generation = self._generation
        for idx in sorted(wanted - self._loaded, key=lambda i: abs(i - self._current)):
            self._loaded.add(idx)

            def on_ready(pb, idx=idx):
                if generation != self._generation or idx not in self._loaded:
                    return
                if pb is None:
                    return
                self._pictures[idx].set_pixbuf(pb)
                self._image_sizes[idx] = _image_size(pb)
                self._set_height(idx, reader_logic.strip_height(*self._image_sizes[idx], self._width))

            if self._loader is not None:
                self._loader(self._pages[idx], on_ready)
            else:
                page = self._pages[idx]
                image_loader.load_image_async(page.image_url or page.url, on_ready)

    def _on_scroll_changed(self, adj):
        if not self._pictures:
            return
        tops = self._tops()
        # The strip crossing the middle of the screen is the one being read.
        idx = reader_logic.page_at_offset(tops, adj.get_value() + adj.get_page_size() / 2)
        if idx != self._current:
            self._current = idx
            self._update_window()
            if self._on_page_visible:
                self._on_page_visible(idx)

        if self._transitioning:
            return
        # Only trigger when practically at the very bottom
        if adj.get_upper() > adj.get_page_size() and \
                adj.get_value() + adj.get_page_size() >= adj.get_upper() - 5:
            if self._on_end:
                self._transitioning = True
                self._on_end()
                # reset guard after some time so we don't spam if they stay at bottom without loading next
                GLib.timeout_add(1000, lambda: setattr(self, "_transitioning", False) or False)


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
        self._tap_layout = "standard"
        self._wheel_turns = False
        self._webtoon_padding = 0
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

        # Tap zones. One click gesture on the overlay rather than three
        # invisible buttons on top of the page: buttons swallowed the mouse
        # wheel and drags, so a fit-width page could not be scrolled. A click
        # that turns into a drag never emits "released", so panning does not
        # turn the page.
        self._tap_gesture = Gtk.GestureClick.new()
        self._tap_gesture.set_button(Gdk.BUTTON_PRIMARY)
        self._tap_gesture.connect("released", self._on_paged_click)
        self._paged_overlay.add_controller(self._tap_gesture)

        # Optional wheel page turns. Capture phase, so the decision is made
        # before the scrolled window consumes the event; returning False
        # lets a tall page scroll normally.
        self._wheel_controller = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
        )
        self._wheel_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._wheel_controller.connect("scroll", self._on_paged_wheel)
        # A touchpad swipe arrives as begin, many small scrolls, end. One
        # swipe should turn one page however long it lasts, so remember
        # whether this gesture already turned.
        self._wheel_controller.connect("scroll-begin", self._on_wheel_gesture_begin)
        self._wheel_controller.connect("scroll-end", self._on_wheel_gesture_end)
        self._paged_overlay.add_controller(self._wheel_controller)
        self._last_wheel_turn = 0.0
        self._wheel_gesture_active = False
        self._wheel_gesture_turned = False
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
        self._webtoon_gesture.set_button(Gdk.BUTTON_PRIMARY)
        # "released", not "pressed": a scroll-bar drag cancels the click, so
        # dragging to scroll no longer flashes the menu.
        self._webtoon_gesture.connect(
            "released", lambda g, n, x, y: self._toggle_ui() if n == 1 else None
        )
        self._webtoon_overlay.add_controller(self._webtoon_gesture)

        self._reader_stack.add_named(self._webtoon_overlay, "webtoon")
        
        # Set background to main overlay
        self._main_overlay.set_child(self._reader_stack)
        self._main_overlay.add_overlay(self._build_chapter_end_card())

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

        next_ch_btn = Gtk.Button(icon_name="media-skip-forward-symbolic")
        next_ch_btn.set_tooltip_text("Next chapter (N)")
        next_ch_btn.connect("clicked", lambda *_: self._go_to_chapter(1))
        prev_ch_btn = Gtk.Button(icon_name="media-skip-backward-symbolic")
        prev_ch_btn.set_tooltip_text("Previous chapter (P)")
        prev_ch_btn.connect("clicked", lambda *_: self._go_to_chapter(-1))

        settings_btn = Gtk.MenuButton(icon_name="preferences-system-symbolic")
        settings_btn.set_tooltip_text("Reader settings")
        settings_btn.set_popover(self._build_settings_popover())
        self._top_bar.pack_end(settings_btn)
        self._top_bar.pack_end(next_ch_btn)
        self._top_bar.pack_end(prev_ch_btn)

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

        # The direction is remembered per series, like Android; the global
        # default lives in Settings -> Reader.
        hint_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._direction_hint = Gtk.Label()
        self._direction_hint.add_css_class("dim-label")
        self._direction_hint.add_css_class("caption")
        self._direction_hint.set_hexpand(True)
        self._direction_hint.set_halign(Gtk.Align.START)
        self._direction_hint.set_wrap(True)
        hint_row.append(self._direction_hint)
        self._direction_reset_btn = Gtk.Button(label="Use Default")
        self._direction_reset_btn.add_css_class("flat")
        self._direction_reset_btn.add_css_class("caption")
        self._direction_reset_btn.connect("clicked", lambda *_: self._clear_series_direction())
        hint_row.append(self._direction_reset_btn)
        box.append(hint_row)

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

        self._wheel_turns_toggle = Gtk.CheckButton(label="Scroll Wheel Turns Pages")
        self._wheel_turns_toggle.set_tooltip_text(
            "In paged mode, scroll past the end of a page to turn it"
        )
        self._wheel_turns_toggle.connect("toggled", self._set_wheel_turns)
        box.append(self._wheel_turns_toggle)

        # Tap zones
        tap_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tap_label = Gtk.Label(label="Tap Zones")
        tap_label.set_hexpand(True)
        tap_label.set_halign(Gtk.Align.START)
        tap_row.append(tap_label)
        self._tap_layout_dropdown = Gtk.DropDown.new_from_strings(
            [self._TAP_LAYOUT_NAMES[k] for k in reader_logic.TAP_LAYOUTS]
        )
        self._tap_layout_dropdown.set_tooltip_text(
            "Standard: left/right thirds turn pages. Kindle: top third opens the menu. "
            "Edges: narrow side strips turn pages. Off: clicks only open the menu."
        )
        self._tap_layout_dropdown.connect("notify::selected", self._set_tap_layout)
        tap_row.append(self._tap_layout_dropdown)
        box.append(tap_row)

        # Webtoon side padding
        pad_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pad_label = Gtk.Label(label="Webtoon Side Padding")
        pad_label.set_hexpand(True)
        pad_label.set_halign(Gtk.Align.START)
        pad_row.append(pad_label)
        self._padding_dropdown = Gtk.DropDown.new_from_strings(
            ["None" if p == 0 else f"{p}%" for p in reader_logic.WEBTOON_PADDINGS]
        )
        self._padding_dropdown.set_tooltip_text("Narrow webtoon strips on wide windows")
        self._padding_dropdown.connect("notify::selected", self._set_webtoon_padding)
        pad_row.append(self._padding_dropdown)
        box.append(pad_row)

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
        self._tap_layout = self._db.get_setting("reader_tap_layout", "standard")
        if self._tap_layout not in reader_logic.TAP_LAYOUTS:
            self._tap_layout = "standard"
        self._wheel_turns = self._db.get_setting("reader_wheel_turns", "0") == "1"
        try:
            self._webtoon_padding = int(self._db.get_setting("reader_webtoon_padding", "0"))
        except ValueError:
            self._webtoon_padding = 0
        if self._webtoon_padding not in reader_logic.WEBTOON_PADDINGS:
            self._webtoon_padding = 0
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
        if hasattr(self, "_wheel_turns_toggle"):
            self._wheel_turns_toggle.set_active(self._wheel_turns)
        if hasattr(self, "_tap_layout_dropdown"):
            self._tap_layout_dropdown.set_selected(reader_logic.TAP_LAYOUTS.index(self._tap_layout))
        if hasattr(self, "_padding_dropdown"):
            self._padding_dropdown.set_selected(
                reader_logic.WEBTOON_PADDINGS.index(self._webtoon_padding)
            )

        if hasattr(self, "_zoom_label"):
            self._zoom_label.set_text(f"{round(self._zoom * 100)}%")
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
        for view in (self._page_view, self._double_page_view):
            view.configure(self._scale_type, self._crop_borders, self._zoom)
        self._webtoon_view.set_padding(self._webtoon_padding)
        self._webtoon_view.set_zoom(self._zoom)

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
        # Capture phase, so reader keys work wherever focus sits inside the
        # reader, before a focused child's own key bindings can claim them.
        # Popovers and Ctrl/Alt shortcuts are passed through below.
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _focus_in_popover(self) -> bool:
        """True while a settings popover has focus, so its own keys still work."""
        root = self.get_root()
        widget = root.get_focus() if root is not None else None
        while widget is not None:
            if isinstance(widget, Gtk.Popover):
                return True
            widget = widget.get_parent()
        return False

    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        if self._focus_in_popover():
            return False
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            # Leave Ctrl/Alt shortcuts (Ctrl+W, Ctrl+?, ...) to the window.
            return False
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
        if keyval in (Gdk.KEY_Page_Down, Gdk.KEY_KP_Page_Down):
            self._scroll_or_turn(1)
            return True
        if keyval in (Gdk.KEY_Page_Up, Gdk.KEY_KP_Page_Up, Gdk.KEY_BackSpace):
            self._scroll_or_turn(-1)
            return True
        if keyval in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
            self._jump_to_page(0)
            return True
        if keyval in (Gdk.KEY_End, Gdk.KEY_KP_End):
            self._jump_to_page(len(self._pages) - 1)
            return True
        if keyval in (Gdk.KEY_f, Gdk.KEY_F, Gdk.KEY_F11):
            self._fullscreen_toggle.set_active(not self._fullscreen_enabled)
            return True
        if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self._set_zoom(self._zoom + 0.1)
            return True
        if keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self._set_zoom(self._zoom - 0.1)
            return True
        if keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
            self._set_zoom(1.0)
            return True
        if keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self._go_to_chapter(1)
            return True
        if keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self._go_to_chapter(-1)
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
        self._hide_chapter_end()

        wanted = self._series_direction(manga)
        if wanted != self._direction:
            self._switch_direction(wanted)
            self._sync_settings_controls()
        self._update_direction_hint()

        ch_num = f"Ch.{chapter.chapter_number:g}" if chapter.chapter_number >= 0 else chapter.title
        self._chapter_title.set_title(manga.title)
        if is_incognito(self._db):
            ch_num = f"{ch_num} · Incognito"
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
            self._show_webtoon()
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
            self._begin_page_load(token, 2 if right_page is not None else 1)
            self._load_page_pixbuf(left_page, self._counting(token, set_left))
            if right_page is not None:
                self._load_page_pixbuf(right_page, self._counting(token, set_right))
            return

        # Single-page load
        page = self._pages[idx]
        self._page_view.set_loading()

        def set_single(pb):
            if token != self._render_token:
                return
            self._page_view.set_pixbuf(pb)

        self._begin_page_load(token, 1)
        self._load_page_pixbuf(page, self._counting(token, set_single))

    # How long a page may take before the spinner shows. A cached page
    # arrives well inside this, so turning through cached pages never
    # flashes a spinner.
    SPINNER_DELAY_MS = 150

    def _begin_page_load(self, token, parts):
        self._page_load_pending = parts
        self._page_load_token = token
        if getattr(self, "_spinner_timer", 0):
            GLib.source_remove(self._spinner_timer)
        self._spinner_timer = GLib.timeout_add(self.SPINNER_DELAY_MS, self._maybe_show_spinner, token)

    def _maybe_show_spinner(self, token):
        self._spinner_timer = 0
        if token == self._render_token and self._page_load_pending > 0:
            self._page_spinner.set_visible(True)
            self._page_spinner.start()
        return False

    def _counting(self, token, callback):
        """Wrap a page callback so the spinner hides once every part arrived."""
        def wrapped(pb):
            if token == getattr(self, "_page_load_token", None):
                self._page_load_pending -= 1
                if self._page_load_pending <= 0:
                    if getattr(self, "_spinner_timer", 0):
                        GLib.source_remove(self._spinner_timer)
                        self._spinner_timer = 0
                    self._page_spinner.stop()
                    self._page_spinner.set_visible(False)
            callback(pb)
        return wrapped

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
        if self._chapter_end_visible():
            # Past the end card: the next "page" is the next chapter.
            self._go_to_chapter(1)
            return
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
        if self._chapter_end_visible():
            self._hide_chapter_end()
            return
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

    def _on_paged_click(self, gesture, n_press, x, y):
        if n_press != 1:
            return
        width = self._paged_overlay.get_width()
        if width <= 0:
            return
        height = self._paged_overlay.get_height() or 1
        action = reader_logic.tap_action(
            x / width,
            self._direction == ReadingDirection.RTL,
            self._tap_invert,
            layout=self._tap_layout,
            y_fraction=y / height,
        )
        if action == "next":
            self._next_page()
        elif action == "prev":
            self._prev_page()
        else:
            self._toggle_ui()

    def _show_webtoon(self):
        self._webtoon_view.set_pages(
            self._pages,
            on_page_visible=self._on_webtoon_page,
            loader=self._load_page_pixbuf,
            start_index=self._current_page,
        )
        self._update_page_label(self._current_page)

    def _on_webtoon_page(self, idx):
        """Webtoon equivalent of _show_page's bookkeeping, minus the drawing."""
        if idx < len(self._pages) - 1 and self._chapter_end_visible():
            # Scrolled back up from the end: the reader is staying.
            self._hide_chapter_end()
        self._current_page = idx
        self._update_page_label(idx)
        self._save_progress(idx)

    def _update_page_label(self, idx):
        if self._pages:
            self._page_label.set_text(f"{idx + 1} / {len(self._pages)}")

    def _on_slider_changed(self, slider):
        if self._slider_changing:
            return
        idx = int(slider.get_value())
        if idx != self._current_page:
            self._show_page(idx)

    def _on_chapter_finished(self):
        """
        All pages read: mark the chapter read and show the end card.

        The next chapter no longer opens straight away. Like Android's
        transition page, one more "next" (tap, key or the button) moves on,
        and "previous" or Stay keeps reading this one.
        """
        if self._chapter and self._chapter.id and not is_incognito(self._db):
            if not getattr(self._chapter, 'read', False):
                self._db.mark_chapter_read(self._chapter.id, len(self._pages) - 1)
                self._chapter.read = True
        self._show_chapter_end()

    def _build_chapter_end_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("card")
        card.add_css_class("reader-end-card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        for side in ("start", "end", "top", "bottom"):
            getattr(card, f"set_margin_{side}")(24)

        heading = Gtk.Label(label="Finished")
        heading.add_css_class("dim-label")
        card.append(heading)
        self._end_finished_label = Gtk.Label()
        self._end_finished_label.add_css_class("title-3")
        self._end_finished_label.set_wrap(True)
        self._end_finished_label.set_justify(Gtk.Justification.CENTER)
        card.append(self._end_finished_label)
        self._end_next_label = Gtk.Label()
        self._end_next_label.set_wrap(True)
        self._end_next_label.set_justify(Gtk.Justification.CENTER)
        card.append(self._end_next_label)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.CENTER)
        buttons.set_margin_top(8)
        stay_btn = Gtk.Button(label="Stay")
        stay_btn.connect("clicked", lambda *_: self._hide_chapter_end())
        buttons.append(stay_btn)
        self._end_next_btn = Gtk.Button(label="Next Chapter")
        self._end_next_btn.add_css_class("suggested-action")
        self._end_next_btn.connect("clicked", lambda *_: self._go_to_chapter(1))
        buttons.append(self._end_next_btn)
        card.append(buttons)

        card.set_visible(False)
        self._chapter_end_card = card
        return card

    def _show_chapter_end(self):
        nxt = None
        if self._manga and self._manga.id and self._chapter:
            nxt = reader_logic.adjacent_chapter(
                self._db.get_chapters(self._manga.id), self._chapter, 1
            )
        self._end_finished_label.set_text(reader_logic.chapter_label(self._chapter))
        if nxt is None:
            self._end_next_label.set_text("No more chapters")
            self._end_next_btn.set_sensitive(False)
        else:
            self._end_next_label.set_text(f"Next: {reader_logic.chapter_label(nxt)}")
            self._end_next_btn.set_sensitive(True)
        self._chapter_end_card.set_visible(True)

    def _hide_chapter_end(self):
        if hasattr(self, "_chapter_end_card"):
            self._chapter_end_card.set_visible(False)

    def _chapter_end_visible(self) -> bool:
        return hasattr(self, "_chapter_end_card") and self._chapter_end_card.get_visible()

    # ── Extra navigation ─────────────────────────────────────────────────

    def _scroll_or_turn(self, direction: int):
        """Page Down/Up: scroll a webtoon by a screen, turn a page otherwise."""
        if self._mode == "webtoon":
            adj = self._webtoon_view.get_vadjustment()
            adj.set_value(adj.get_value() + direction * adj.get_page_increment())
        elif direction > 0:
            self._next_page()
        else:
            self._prev_page()

    def _jump_to_page(self, idx):
        if not self._pages:
            return
        idx = max(0, min(idx, len(self._pages) - 1))
        self._hide_chapter_end()
        if self._mode == "webtoon":
            self._webtoon_view.scroll_to_page(idx)
        else:
            self._show_page(idx)

    def _on_wheel_gesture_begin(self, *_):
        self._wheel_gesture_active = True
        self._wheel_gesture_turned = False

    def _on_wheel_gesture_end(self, *_):
        self._wheel_gesture_active = False

    def _on_paged_wheel(self, controller, dx, dy):
        if not self._wheel_turns or self._mode != "paged" or not self._pages:
            return False
        view = self._double_page_view if self._effective_layout() == "double" else self._page_view
        adj = view.get_vadjustment()
        at_start = adj.get_value() <= 0.5
        at_end = adj.get_value() + adj.get_page_size() >= adj.get_upper() - 0.5
        action = reader_logic.wheel_turn(dy, at_start, at_end)
        if action is None:
            return False
        if self._wheel_gesture_active:
            # Touchpad swipe: one turn for the whole gesture.
            if self._wheel_gesture_turned:
                return True
            self._wheel_gesture_turned = True
        else:
            # Mouse wheel: no gesture bounds, so space the turns out instead.
            now = time.monotonic()
            if now - self._last_wheel_turn < 0.35:
                return True
            self._last_wheel_turn = now
        if action == "next":
            self._next_page()
        else:
            self._prev_page()
        return True

    def _go_to_next_chapter(self):
        self._go_to_chapter(1)

    def _go_to_chapter(self, step: int):
        """
        Open the chapter ``step`` places away in reading order (-1 = previous).

        Order comes from the source's own listing, so chapters without a
        number are reached too; sorting by number skipped them.
        """
        if getattr(self, "_transitioning_chapter", False):
            return
        if not self._manga or not self._manga.id or not self._chapter:
            return
        target = reader_logic.adjacent_chapter(
            self._db.get_chapters(self._manga.id), self._chapter, step
        )
        if target is None:
            notify(self, "This is the last chapter" if step > 0 else "This is the first chapter")
            return
        self._transitioning_chapter = True
        self.load_chapter(self._manga, target, force_start=True)
        # Reset flag after some time so that we don't block subsequent transitions
        GLib.timeout_add(1000, lambda: setattr(self, "_transitioning_chapter", False) or False)

    def _save_progress(self, page_idx: int):
        if is_incognito(self._db):
            # Incognito: no saved page, no history entry, no tracker update.
            return
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
        if self._manga is not None and self._manga.id:
            # Changing direction while reading sets it for this series only;
            # the default for everything else stays as it is.
            self._db.set_manga_reading_mode(self._manga.id, direction.value)
        else:
            self._persist_reader_setting("reading_direction", direction.value)
        self._switch_direction(direction)
        self._update_direction_hint()

    def _default_direction(self) -> ReadingDirection:
        try:
            return ReadingDirection(self._db.get_setting("reading_direction", ReadingDirection.RTL.value))
        except ValueError:
            return ReadingDirection.RTL

    def _series_direction(self, manga) -> ReadingDirection:
        """This series' saved direction, or the default when none is saved."""
        if manga is not None and manga.id:
            saved = self._db.get_manga_reading_mode(manga.id)
            if saved:
                try:
                    return ReadingDirection(saved)
                except ValueError:
                    pass
        return self._default_direction()

    def _clear_series_direction(self):
        if self._manga is not None and self._manga.id:
            self._db.set_manga_reading_mode(self._manga.id, "")
        direction = self._default_direction()
        self._switch_direction(direction)
        self._sync_settings_controls()
        self._update_direction_hint()

    def _update_direction_hint(self):
        if not hasattr(self, "_direction_hint"):
            return
        saved = bool(self._manga is not None and self._manga.id
                     and self._db.get_manga_reading_mode(self._manga.id))
        self._direction_hint.set_text(
            "Saved for this series" if saved else "Using the default from Settings → Reader"
        )
        self._direction_reset_btn.set_visible(saved)

    def _switch_direction(self, direction: ReadingDirection):
        """Apply a reading direction to the open chapter without saving it."""
        self._direction = direction
        if direction == ReadingDirection.WEBTOON:
            self._mode = "webtoon"
            if self._pages:
                self._show_webtoon()
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

    _TAP_LAYOUT_NAMES = {
        "standard": "Standard",
        "kindle": "Kindle",
        "edges": "Edges",
        "off": "Off",
    }

    def _set_tap_layout(self, dropdown, *_):
        if self._syncing_prefs:
            return
        self._tap_layout = reader_logic.TAP_LAYOUTS[dropdown.get_selected()]
        self._persist_reader_setting("reader_tap_layout", self._tap_layout)

    def _set_wheel_turns(self, btn):
        if self._syncing_prefs:
            return
        self._wheel_turns = btn.get_active()
        self._persist_reader_setting("reader_wheel_turns", "1" if self._wheel_turns else "0")

    def _set_webtoon_padding(self, dropdown, *_):
        if self._syncing_prefs:
            return
        self._webtoon_padding = reader_logic.WEBTOON_PADDINGS[dropdown.get_selected()]
        self._persist_reader_setting("reader_webtoon_padding", str(self._webtoon_padding))
        self._webtoon_view.set_padding(self._webtoon_padding)

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
        self._zoom = reader_logic.clamp_zoom(round(zoom, 2))
        self._zoom_label.set_text(f"{round(self._zoom * 100)}%")
        self._persist_reader_setting("reader_zoom", f"{self._zoom:.2f}")
        # The views resize in place; no need to reload the page.
        self._apply_scale_and_crop()

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
