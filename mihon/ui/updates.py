"""
Updates view - checks library manga for newly released chapters.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib
import threading
import time

from ..core.database import get_db
from ..core.library_updater import LibraryUpdater, LibraryUpdateSummary
from .widgets import EmptyState, LoadingSpinner


class UpdatesView(Gtk.Box):
    """
    Library updates page with a manual "check updates" action.
    """

    def __init__(self, on_manga_selected=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_manga_selected = on_manga_selected
        self._db = get_db()
        self._updater = LibraryUpdater()
        self._checking = False
        self._last_checked_at = None
        self._did_initial_refresh = False

        self._build_ui()
        self.refresh_cached()

    def _build_ui(self):
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.set_margin_start(16)
        header_box.set_margin_end(16)
        header_box.set_margin_top(8)
        header_box.set_margin_bottom(8)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)

        title = Gtk.Label(label="Updates")
        title.add_css_class("title-3")
        title.set_xalign(0)
        title_box.append(title)

        self._status_label = Gtk.Label(label="Shows newly fetched chapters for your library")
        self._status_label.add_css_class("dim-label")
        self._status_label.set_xalign(0)
        title_box.append(self._status_label)
        header_box.append(title_box)

        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        header_box.append(self._spinner)

        self._check_btn = Gtk.Button(label="Check Updates")
        self._check_btn.add_css_class("suggested-action")
        self._check_btn.connect("clicked", self._on_check_updates_clicked)
        header_box.append(self._check_btn)

        self.append(header_box)
        self.append(Gtk.Separator())

        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.append(self._stack)

        self._loading = LoadingSpinner("Checking for new chapters...")
        self._stack.add_named(self._loading, "loading")

        self._empty = EmptyState(
            "view-refresh-symbolic",
            "No updates yet",
            "Tap 'Check Updates' to scan your library",
        )
        self._stack.add_named(self._empty, "empty")

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._list.set_margin_start(16)
        self._list.set_margin_end(16)
        self._list.set_margin_top(16)
        self._list.set_margin_bottom(16)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self._list)
        self._stack.add_named(scroll, "list")

    def refresh_cached(self):
        """
        Refresh from local DB unread counts without hitting network.
        Useful when entering the tab before a full update check.
        """
        if self._checking:
            return

        def load():
            manga = self._db.get_library()
            unread = [m for m in manga if m.unread_count > 0]
            GLib.idle_add(self._render_cached_unread, unread)

        threading.Thread(target=load, daemon=True).start()

    def ensure_initial_check(self):
        """Run one automatic check the first time the Updates tab is opened."""
        if self._did_initial_refresh or self._checking:
            return
        self._did_initial_refresh = True
        self._start_update_check()

    def _on_check_updates_clicked(self, *_):
        self._start_update_check()

    def _start_update_check(self):
        if self._checking:
            return

        self._checking = True
        self._check_btn.set_sensitive(False)
        self._spinner.set_visible(True)
        self._spinner.start()
        self._status_label.set_text("Starting library update check...")
        self._stack.set_visible_child_name("loading")

        def run():
            summary = self._updater.check_updates(progress_cb=self._on_progress)
            GLib.idle_add(self._on_check_complete, summary)

        threading.Thread(target=run, daemon=True).start()

    def _on_progress(self, current: int, total: int, manga):
        GLib.idle_add(
            self._status_label.set_text,
            f"Checking {current}/{max(total, 1)}: {manga.title}",
        )

    def _on_check_complete(self, summary: LibraryUpdateSummary):
        self._checking = False
        self._check_btn.set_sensitive(True)
        self._spinner.stop()
        self._spinner.set_visible(False)
        self._last_checked_at = time.time()

        status = (
            f"Checked {summary.checked_manga} manga  •  "
            f"{summary.updated_manga} updated  •  "
            f"{summary.new_chapters} new chapters"
        )
        if summary.failures:
            status += f"  •  {summary.failures} failed"
        self._status_label.set_text(status)

        if summary.results:
            self._render_update_results(summary)
        else:
            # Still show cached unread as fallback after a check.
            self.refresh_cached()

    def _render_cached_unread(self, unread_manga):
        if self._checking:
            return
        self._clear_list()
        if not unread_manga:
            self._stack.set_visible_child_name("empty")
            return

        for manga in unread_manga:
            row = Adw.ActionRow(title=manga.title)
            row.set_subtitle(f"{manga.unread_count} unread chapters")
            row.add_prefix(Gtk.Image.new_from_icon_name("mail-unread-symbolic"))
            arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
            arrow.add_css_class("dim-label")
            row.add_suffix(arrow)
            row.set_activatable(True)
            row.connect("activated", lambda _r, m=manga: self._open_manga(m))
            self._list.append(row)

        self._stack.set_visible_child_name("list")

    def _render_update_results(self, summary: LibraryUpdateSummary):
        self._clear_list()

        for result in summary.results:
            manga = result.manga
            count = len(result.new_chapters)
            latest = result.new_chapters[0] if result.new_chapters else None
            latest_text = self._chapter_label(latest) if latest else "New chapters"

            row = Adw.ActionRow(title=manga.title)
            row.set_subtitle(f"{count} new chapters  •  Latest: {latest_text}")
            row.add_prefix(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))

            badge = Gtk.Label(label=str(count))
            badge.add_css_class("unread-badge")
            badge.set_valign(Gtk.Align.CENTER)
            row.add_suffix(badge)

            arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
            arrow.add_css_class("dim-label")
            row.add_suffix(arrow)
            row.set_activatable(True)
            row.connect("activated", lambda _r, m=manga: self._open_manga(m))
            self._list.append(row)

        if summary.errors:
            err_row = Adw.ActionRow(title="Some sources failed")
            err_row.set_subtitle(summary.errors[0])
            err_row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
            self._list.append(err_row)

        self._stack.set_visible_child_name("list")

    def _open_manga(self, manga):
        if self._on_manga_selected:
            self._on_manga_selected(manga)

    def _clear_list(self):
        child = self._list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list.remove(child)
            child = nxt

    @staticmethod
    def _chapter_label(chapter):
        if not chapter:
            return "Unknown"
        if chapter.chapter_number is not None and chapter.chapter_number >= 0:
            return f"Chapter {chapter.chapter_number:g}"
        return chapter.title or "Unknown"
