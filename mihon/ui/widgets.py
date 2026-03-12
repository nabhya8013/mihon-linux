"""
Shared UI widgets for Mihon Linux.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GdkPixbuf, Pango, GLib, Gdk
from ..core.models import Manga
from ..core import image_loader


class MangaCard(Gtk.Box):
    """
    A manga cover card shown in grid views.
    Shows cover image, title, and unread badge.
    """
    CARD_WIDTH = 150
    CARD_HEIGHT = 220

    def __init__(self, manga: Manga, on_click=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.manga = manga
        self._on_click = on_click
        self.set_size_request(self.CARD_WIDTH, -1)
        self.add_css_class("manga-card")

        # Overlay for badge
        overlay = Gtk.Overlay()

        # Cover image
        self._image = Gtk.Picture()
        self._image.set_content_fit(Gtk.ContentFit.COVER)
        self._image.set_size_request(self.CARD_WIDTH, self.CARD_HEIGHT)
        self._image.add_css_class("manga-cover")

        # Placeholder
        self._placeholder = Gtk.Box()
        self._placeholder.set_size_request(self.CARD_WIDTH, self.CARD_HEIGHT)
        self._placeholder.add_css_class("manga-cover-placeholder")
        icon = Gtk.Image.new_from_icon_name("image-x-generic-symbolic")
        icon.set_pixel_size(48)
        icon.set_vexpand(True)
        icon.set_hexpand(True)
        self._placeholder.append(icon)

        overlay.set_child(self._placeholder)

        # Unread badge
        if manga.unread_count > 0:
            badge = Gtk.Label(label=str(manga.unread_count))
            badge.add_css_class("unread-badge")
            badge.set_halign(Gtk.Align.END)
            badge.set_valign(Gtk.Align.START)
            badge.set_margin_end(6)
            badge.set_margin_top(6)
            overlay.add_overlay(badge)

        self.append(overlay)

        # Title label
        title = Gtk.Label(label=manga.title)
        title.set_wrap(True)
        title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.set_max_width_chars(15)
        title.set_lines(2)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_justify(Gtk.Justification.CENTER)
        title.set_margin_top(4)
        title.set_margin_start(4)
        title.set_margin_end(4)
        title.set_margin_bottom(4)
        title.add_css_class("manga-card-title")
        self.append(title)

        # Hover
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self.add_css_class("manga-card-hover"))
        motion.connect("leave", lambda *_: self.remove_css_class("manga-card-hover"))
        self.add_controller(motion)

        # Load cover
        self._load_cover(overlay)

    def _load_cover(self, overlay):
        url = self.manga.cover_local_path or self.manga.cover_url
        if not url:
            return
        if self.manga.cover_local_path and GLib.file_test(self.manga.cover_local_path, GLib.FileTest.EXISTS):
            pixbuf = image_loader.load_local_image(
                self.manga.cover_local_path, self.CARD_WIDTH, self.CARD_HEIGHT
            )
            if pixbuf:
                self._set_pixbuf(overlay, pixbuf)
            return
        image_loader.load_image_async(
            self.manga.cover_url,
            lambda pb: self._set_pixbuf(overlay, pb),
            width=self.CARD_WIDTH,
            height=self.CARD_HEIGHT,
        )

    def _set_pixbuf(self, overlay, pixbuf):
        if pixbuf:
            self._image.set_pixbuf(pixbuf)
            overlay.set_child(self._image)


class LoadingSpinner(Gtk.Box):
    def __init__(self, label="Loading..."):
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            vexpand=True,
            hexpand=True,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
        )
        spinner = Gtk.Spinner()
        spinner.set_size_request(48, 48)
        spinner.start()
        self.append(spinner)
        lbl = Gtk.Label(label=label)
        lbl.add_css_class("dim-label")
        self.append(lbl)


class EmptyState(Gtk.Box):
    def __init__(self, icon_name: str, title: str, subtitle: str = ""):
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            vexpand=True,
            hexpand=True,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
        )
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(80)
        icon.add_css_class("dim-label")
        self.append(icon)

        t = Gtk.Label(label=title)
        t.add_css_class("title-2")
        self.append(t)
        self._title_label = t

        if subtitle:
            s = Gtk.Label(label=subtitle)
            s.add_css_class("dim-label")
            s.set_wrap(True)
            s.set_max_width_chars(40)
            s.set_justify(Gtk.Justification.CENTER)
            self.append(s)

    def set_title(self, title: str):
        self._title_label.set_label(title)


class MangaGridView(Gtk.ScrolledWindow):
    """Scrollable grid of manga cards."""

    COLUMNS = 5

    def __init__(self, on_manga_click=None):
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)
        self._on_manga_click = on_manga_click

        self._flow = Gtk.FlowBox()
        self._flow.set_valign(Gtk.Align.START)
        self._flow.set_max_children_per_line(8)
        self._flow.set_min_children_per_line(2)
        self._flow.set_column_spacing(8)
        self._flow.set_row_spacing(8)
        self._flow.set_margin_start(16)
        self._flow.set_margin_end(16)
        self._flow.set_margin_top(16)
        self._flow.set_margin_bottom(16)
        self._flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flow.set_homogeneous(True)
        self._flow.set_activate_on_single_click(True)
        self._flow.connect("child-activated", self._on_child_activated)
        self.set_child(self._flow)

    def _on_child_activated(self, flowbox, child):
        """Handle click on a FlowBoxChild — find the MangaCard inside and trigger its callback."""
        card = child.get_child()
        if isinstance(card, MangaCard) and self._on_manga_click:
            self._on_manga_click(card.manga)

    def set_manga(self, manga_list):
        # Clear
        child = self._flow.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._flow.remove(child)
            child = next_child

        for manga in manga_list:
            card = MangaCard(manga, on_click=self._on_manga_click)
            self._flow.append(card)

    def append_manga(self, manga_list):
        for manga in manga_list:
            card = MangaCard(manga, on_click=self._on_manga_click)
            self._flow.append(card)
