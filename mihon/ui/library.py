"""
Library view - shows manga in the user's library with advanced controls.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gdk, GObject
import threading
from ..core.database import get_db
from ..core.models import Manga, ReadingStatus
from .widgets import MangaGridView, EmptyState, LoadingSpinner
import logging
from .library_state import LibraryPreferences, SORT_OPTIONS, DISPLAY_MODES
from .library_presenter import LibraryPresenter
from .notify import notify, notify_retry

logger = logging.getLogger("library_view")


class LibraryView(Gtk.Box):
    """
    Main library page showing manga in user's collection.
    Includes search, sorting, display modes, advanced filters, batch actions,
    and per-category preference persistence.
    """

    def __init__(self, on_manga_selected=None, on_show_downloads=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._on_manga_selected = on_manga_selected
        self._on_show_downloads = on_show_downloads
        self._db = get_db()
        # All library data and filter state lives in the presenter; this view
        # only renders whatever the presenter currently says is visible.
        self._presenter = LibraryPresenter(self._db)
        self._syncing_controls = False

        self._build_ui()
        self._presenter.subscribe(self._on_presenter_changed)
        self._sync_controls_from_prefs()
        self.reload()

    def _build_ui(self):
        # Header controls
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.set_margin_start(16)
        header_box.set_margin_end(16)
        header_box.set_margin_top(8)
        header_box.set_margin_bottom(8)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Search library...")
        self._search.set_hexpand(True)
        self._search.connect("search-changed", self._on_search_changed)
        header_box.append(self._search)

        filter_btn = Gtk.MenuButton()
        filter_btn.set_icon_name("funnel-symbolic")
        filter_btn.set_tooltip_text("Advanced filters")
        filter_btn.set_popover(self._build_filter_menu())
        header_box.append(filter_btn)

        self._sort_btn = Gtk.MenuButton()
        self._sort_btn.set_icon_name("view-sort-ascending-symbolic")
        self._sort_btn.set_tooltip_text("Sort options")
        self._sort_btn.set_popover(self._build_sort_menu())
        header_box.append(self._sort_btn)

        self._display_btn = Gtk.MenuButton()
        self._display_btn.set_tooltip_text("Display mode")
        self._display_btn.set_popover(self._build_display_menu())
        header_box.append(self._display_btn)

        batch_btn = Gtk.MenuButton()
        batch_btn.set_icon_name("edit-select-all-symbolic")
        batch_btn.set_tooltip_text("Batch actions for filtered results")
        batch_btn.set_popover(self._build_batch_menu())
        header_box.append(batch_btn)

        manage_categories_btn = Gtk.Button(label="Categories")
        manage_categories_btn.set_tooltip_text("Manage categories")
        manage_categories_btn.connect("clicked", self._open_category_manager)
        header_box.append(manage_categories_btn)

        dl_btn = Gtk.Button(icon_name="folder-download-symbolic")
        dl_btn.set_tooltip_text("Show Downloads")
        if self._on_show_downloads:
            dl_btn.connect("clicked", lambda *_: self._on_show_downloads())
        header_box.append(dl_btn)

        self.append(header_box)

        self._info_label = Gtk.Label()
        self._info_label.set_xalign(0)
        self._info_label.set_margin_start(16)
        self._info_label.set_margin_end(16)
        self._info_label.set_margin_bottom(6)
        self._info_label.add_css_class("dim-label")
        self._set_info("Configure filters, sort, and display. Preferences are saved per category.")
        self.append(self._info_label)

        # Category tabs
        self._tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._tab_bar.add_css_class("linked")
        self._tab_bar.set_margin_start(16)
        self._tab_bar.set_margin_end(16)
        self._tab_bar.set_margin_bottom(4)
        self._tab_scroll = Gtk.ScrolledWindow()
        self._tab_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self._tab_scroll.set_child(self._tab_bar)
        self.append(self._tab_scroll)

        self.append(Gtk.Separator())

        # Content stack
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.append(self._stack)

        self._loading = LoadingSpinner("Loading library...")
        self._stack.add_named(self._loading, "loading")

        self._empty = EmptyState(
            "bookmarks-symbolic",
            "Your library is empty",
            "Browse manga and add them to your library",
        )
        self._stack.add_named(self._empty, "empty")

        self._grid = MangaGridView(on_manga_click=self._on_manga_selected)
        self._stack.add_named(self._grid, "grid")

        self._list_view = Gtk.ListBox()
        self._list_view.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_view.add_css_class("boxed-list")
        self._list_view.set_margin_start(16)
        self._list_view.set_margin_end(16)
        self._list_view.set_margin_top(16)
        self._list_view.set_margin_bottom(16)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_vexpand(True)
        list_scroll.set_child(self._list_view)
        self._stack.add_named(list_scroll, "list")

    def _build_filter_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        lbl = Gtk.Label(label="Reading Status")
        lbl.add_css_class("heading")
        lbl.set_halign(Gtk.Align.START)
        box.append(lbl)

        self._status_filters = {}
        for status in ReadingStatus:
            if status == ReadingStatus.NONE:
                continue
            cb = Gtk.CheckButton(label=status.value.replace("_", " ").title())
            cb.connect("toggled", self._on_filter_controls_changed)
            box.append(cb)
            self._status_filters[status] = cb

        box.append(Gtk.Separator())

        self._unread_only_cb = Gtk.CheckButton(label="Unread Only")
        self._unread_only_cb.connect("toggled", self._on_filter_controls_changed)
        box.append(self._unread_only_cb)

        self._downloaded_only_cb = Gtk.CheckButton(label="Downloaded Only")
        self._downloaded_only_cb.connect("toggled", self._on_filter_controls_changed)
        box.append(self._downloaded_only_cb)

        reset_btn = Gtk.Button(label="Reset Filters")
        reset_btn.add_css_class("flat")
        reset_btn.connect("clicked", self._reset_filters)
        box.append(reset_btn)

        pop.set_child(box)
        return pop

    def _build_sort_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        lbl = Gtk.Label(label="Sort By")
        lbl.add_css_class("heading")
        lbl.set_halign(Gtk.Align.START)
        box.append(lbl)

        self._sort_by_buttons = {}
        first = None
        for key, label in SORT_OPTIONS.items():
            cb = Gtk.CheckButton(label=label)
            if first is None:
                first = cb
            else:
                cb.set_group(first)
            cb.connect("toggled", self._on_sort_by_changed, key)
            box.append(cb)
            self._sort_by_buttons[key] = cb

        self._sort_desc_cb = Gtk.CheckButton(label="Descending")
        self._sort_desc_cb.connect("toggled", self._on_sort_desc_changed)
        box.append(Gtk.Separator())
        box.append(self._sort_desc_cb)

        pop.set_child(box)
        return pop

    def _build_display_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        lbl = Gtk.Label(label="Display Mode")
        lbl.add_css_class("heading")
        lbl.set_halign(Gtk.Align.START)
        box.append(lbl)

        self._display_mode_buttons = {}
        first = None
        for key, label in DISPLAY_MODES.items():
            cb = Gtk.CheckButton(label=label)
            if first is None:
                first = cb
            else:
                cb.set_group(first)
            cb.connect("toggled", self._on_display_mode_changed, key)
            box.append(cb)
            self._display_mode_buttons[key] = cb

        pop.set_child(box)
        return pop

    def _build_batch_menu(self):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        mark_read_btn = Gtk.Button(label="Mark Filtered Chapters Read")
        mark_read_btn.add_css_class("flat")
        mark_read_btn.connect("clicked", lambda *_: self._run_batch_mark_read(pop))
        box.append(mark_read_btn)

        remove_btn = Gtk.Button(label="Remove Filtered from Library")
        remove_btn.add_css_class("flat")
        remove_btn.add_css_class("error")
        remove_btn.connect("clicked", lambda *_: self._run_batch_remove_from_library(pop))
        box.append(remove_btn)

        box.append(Gtk.Separator())

        add_to_cat_btn = Gtk.Button(label="Add Filtered to Current Category")
        add_to_cat_btn.add_css_class("flat")
        add_to_cat_btn.connect("clicked", lambda *_: self._run_batch_add_to_current_category(pop))
        box.append(add_to_cat_btn)

        remove_from_cat_btn = Gtk.Button(label="Remove Filtered from Current Category")
        remove_from_cat_btn.add_css_class("flat")
        remove_from_cat_btn.connect("clicked", lambda *_: self._run_batch_remove_from_current_category(pop))
        box.append(remove_from_cat_btn)

        pop.set_child(box)
        return pop

    def reload(self):
        """Reload manga from database."""
        self._stack.set_visible_child_name("loading")

        def load():
            try:
                loaded = self._presenter.load_from_db()
            except Exception as e:
                GLib.idle_add(self._on_load_failed, str(e))
                return
            GLib.idle_add(self._on_loaded, *loaded)

        threading.Thread(target=load, daemon=True).start()

    def _on_loaded(self, manga, categories, downloaded_ids):
        self._rebuild_category_tabs(categories)
        # set_loaded notifies the presenter's observers, which redraws.
        self._presenter.set_loaded(manga, categories, downloaded_ids)

    def _on_load_failed(self, message: str):
        self._empty.set_title("Could not load your library")
        self._stack.set_visible_child_name("empty")
        notify_retry(self, f"Could not load your library: {message}", self.reload)

    def _on_presenter_changed(self, _presenter):
        """The presenter's visible list changed; redraw from it."""
        self._update_display()

    def _rebuild_category_tabs(self, categories):
        child = self._tab_bar.get_first_child()
        while child:
            next_c = child.get_next_sibling()
            self._tab_bar.remove(child)
            child = next_c

        btn = Gtk.ToggleButton(label="All")
        btn.set_active(self._presenter.category_id is None)
        btn.connect("toggled", self._on_category_tab, None)
        btn.add_css_class("flat")
        self._tab_bar.append(btn)

        for cat in categories:
            b = Gtk.ToggleButton(label=cat.name)
            b.set_active(self._presenter.category_id == cat.id)
            b.connect("toggled", self._on_category_tab, cat.id)
            b.add_css_class("flat")
            self._tab_bar.append(b)

    def _on_category_tab(self, btn, category_id):
        if not btn.get_active():
            return
        if not self._presenter.set_category(category_id):
            return
        self._sync_controls_from_prefs()
        self.reload()

    def _on_search_changed(self, entry):
        self._presenter.set_search_query(entry.get_text())

    def _on_filter_controls_changed(self, *_):
        if self._syncing_controls:
            return
        self._presenter.update_prefs(
            status_filters=[
                status.value
                for status, cb in self._status_filters.items()
                if cb.get_active()
            ],
            unread_only=self._unread_only_cb.get_active(),
            downloaded_only=self._downloaded_only_cb.get_active(),
        )

    def _on_sort_by_changed(self, btn, sort_key):
        if self._syncing_controls or not btn.get_active():
            return
        changed = self._prefs.sort_by != sort_key
        # Count- and date-based sorts are most useful highest-first, so flip
        # the direction when switching onto one of them.
        if changed and sort_key in ("unread_count", "recently_added", "last_read"):
            self._presenter.update_prefs(sort_by=sort_key, sort_desc=True)
            self._sync_controls_from_prefs()
            return
        self._presenter.update_prefs(sort_by=sort_key)

    def _on_sort_desc_changed(self, btn):
        if self._syncing_controls:
            return
        self._presenter.update_prefs(sort_desc=btn.get_active())

    def _on_display_mode_changed(self, btn, mode):
        if self._syncing_controls or not btn.get_active():
            return
        if self._presenter.update_prefs(display_mode=mode):
            self._update_display_icon()

    def _reset_filters(self, *_):
        self._presenter.update_prefs(
            status_filters=[], unread_only=False, downloaded_only=False
        )
        self._sync_controls_from_prefs()

    def _run_batch_mark_read(self, popover):
        popover.popdown()
        manga_ids = self._presenter.visible_ids()
        if not manga_ids:
            self._set_info("Batch mark-read skipped: no filtered manga.")
            return
        self._set_info("Marking filtered chapters as read...")

        def run():
            updated = self._db.mark_manga_chapters_read_bulk(manga_ids)
            GLib.idle_add(self._on_batch_done, f"Marked {updated} chapters as read.")

        threading.Thread(target=run, daemon=True).start()

    def _run_batch_remove_from_library(self, popover):
        popover.popdown()
        manga_ids = self._presenter.visible_ids()
        if not manga_ids:
            self._set_info("Batch remove skipped: no filtered manga.")
            return
        self._set_info("Removing filtered manga from library...")

        def run():
            removed = self._db.remove_from_library_bulk(manga_ids)
            GLib.idle_add(self._on_batch_done, f"Removed {removed} manga from library.")

        threading.Thread(target=run, daemon=True).start()

    def _run_batch_add_to_current_category(self, popover):
        popover.popdown()
        if self._presenter.category_id is None:
            self._set_info("Pick a category tab first, then run this batch action.")
            return
        manga_ids = self._presenter.visible_ids()
        if not manga_ids:
            self._set_info("Batch category add skipped: no filtered manga.")
            return
        category_id = self._presenter.category_id
        category_name = self._presenter.category_name(category_id) or "category"
        self._set_info(f"Adding filtered manga to '{category_name}'...")

        def run():
            self._db.add_manga_to_category_bulk(manga_ids, category_id)
            GLib.idle_add(self._on_batch_done, f"Added filtered manga to '{category_name}'.")

        threading.Thread(target=run, daemon=True).start()

    def _run_batch_remove_from_current_category(self, popover):
        popover.popdown()
        if self._presenter.category_id is None:
            self._set_info("Pick a category tab first, then run this batch action.")
            return
        manga_ids = self._presenter.visible_ids()
        if not manga_ids:
            self._set_info("Batch category remove skipped: no filtered manga.")
            return
        category_id = self._presenter.category_id
        category_name = self._presenter.category_name(category_id) or "category"
        self._set_info(f"Removing filtered manga from '{category_name}'...")

        def run():
            removed = self._db.remove_manga_from_category_bulk(manga_ids, category_id)
            GLib.idle_add(self._on_batch_done, f"Removed {removed} manga-category links from '{category_name}'.")

        threading.Thread(target=run, daemon=True).start()

    def _on_batch_done(self, message: str):
        self._set_info(message)
        notify(self, message)
        self.reload()

    def _update_display(self):
        visible = self._presenter.visible_manga
        if not visible:
            if self._presenter.search_query:
                self._empty.set_title("No results")
            elif self._presenter.is_filtered_empty:
                self._empty.set_title("Nothing matches these filters")
            else:
                self._empty.set_title("Your library is empty")
            self._stack.set_visible_child_name("empty")
            return

        if self._prefs.display_mode == "list":
            self._render_list(visible)
            self._stack.set_visible_child_name("list")
        else:
            self._grid.set_manga(visible)
            self._stack.set_visible_child_name("grid")

    def _render_list(self, manga_list):
        child = self._list_view.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_view.remove(child)
            child = nxt

        for manga in manga_list:
            row = Adw.ActionRow(title=manga.title)
            parts = []
            if manga.author:
                parts.append(manga.author)
            parts.append(f"{manga.chapter_count} chapters")
            parts.append(f"{manga.unread_count} unread")
            if manga.id in self._downloaded_manga_ids:
                parts.append("downloaded")
            row.set_subtitle("  •  ".join(parts))

            icon = Gtk.Image.new_from_icon_name("bookmarks-symbolic")
            row.add_prefix(icon)

            arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
            arrow.add_css_class("dim-label")
            row.add_suffix(arrow)

            row.set_activatable(True)
            row.connect("activated", lambda _r, m=manga: self._on_manga_selected(m) if self._on_manga_selected else None)
            self._list_view.append(row)

    def _sync_controls_from_prefs(self):
        self._syncing_controls = True

        selected_statuses = set(self._prefs.status_filters)
        for status, cb in self._status_filters.items():
            cb.set_active(status.value in selected_statuses)
        self._unread_only_cb.set_active(self._prefs.unread_only)
        self._downloaded_only_cb.set_active(self._prefs.downloaded_only)

        for key, btn in self._sort_by_buttons.items():
            btn.set_active(key == self._prefs.sort_by)
        self._sort_desc_cb.set_active(self._prefs.sort_desc)

        for key, btn in self._display_mode_buttons.items():
            btn.set_active(key == self._prefs.display_mode)
        self._update_display_icon()

        self._syncing_controls = False

    @property
    def _prefs(self):
        """The presenter owns preferences; this keeps the widget code short."""
        return self._presenter.prefs

    def _update_display_icon(self):
        if self._prefs.display_mode == "list":
            self._display_btn.set_icon_name("view-list-symbolic")
        else:
            self._display_btn.set_icon_name("view-grid-symbolic")

    # ── Category management ───────────────────────────────────────────────

    def _open_category_manager(self, *_):
        root = self.get_root()
        if not isinstance(root, Gtk.Window):
            self._set_info("Unable to open category manager: no window context.")
            return

        dialog = Gtk.Dialog(title="Manage Categories", transient_for=root, modal=True)
        dialog.set_default_size(520, 460)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.connect("response", lambda d, _r: d.close())

        content = dialog.get_content_area()
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.append(wrap)

        desc = Gtk.Label(label="Create, rename, reorder, and delete categories.")
        desc.set_xalign(0)
        desc.add_css_class("dim-label")
        wrap.append(desc)

        create_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._cat_new_entry = Gtk.Entry()
        self._cat_new_entry.set_placeholder_text("New category name")
        self._cat_new_entry.set_hexpand(True)
        create_row.append(self._cat_new_entry)
        create_btn = Gtk.Button(label="Add")
        create_btn.add_css_class("suggested-action")
        create_btn.connect("clicked", self._create_category_from_dialog)
        create_row.append(create_btn)
        wrap.append(create_row)

        self._cat_dialog_status = Gtk.Label()
        self._cat_dialog_status.set_xalign(0)
        self._cat_dialog_status.add_css_class("dim-label")
        wrap.append(self._cat_dialog_status)

        self._cat_dialog_list = Gtk.ListBox()
        self._cat_dialog_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._cat_dialog_list.add_css_class("boxed-list")
        cat_scroll = Gtk.ScrolledWindow()
        cat_scroll.set_vexpand(True)
        cat_scroll.set_child(self._cat_dialog_list)
        wrap.append(cat_scroll)

        self._refresh_category_manager_list()
        dialog.present()

    def _create_category_from_dialog(self, *_):
        name = self._cat_new_entry.get_text().strip()
        if not name:
            self._set_cat_dialog_status("Category name is required.")
            return
        try:
            self._db.create_category(name)
            self._cat_new_entry.set_text("")
            self._set_cat_dialog_status(f"Created category '{name}'.")
            self.reload()
            self._refresh_category_manager_list()
        except Exception as e:
            self._set_cat_dialog_status(f"Failed to create '{name}': {e}")

    def _refresh_category_manager_list(self):
        if not hasattr(self, "_cat_dialog_list"):
            return
        child = self._cat_dialog_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._cat_dialog_list.remove(child)
            child = nxt

        categories = self._db.get_categories()
        for idx, cat in enumerate(categories):
            row = Gtk.ListBoxRow()
            # Remember which category this row is, so a drop can identify both
            # ends of the move.
            row.category_id = cat.id
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            row_box.set_margin_top(6)
            row_box.set_margin_bottom(6)

            handle = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
            handle.set_tooltip_text("Drag to reorder")
            row_box.append(handle)

            name_entry = Gtk.Entry()
            name_entry.set_text(cat.name)
            name_entry.set_hexpand(True)
            row_box.append(name_entry)

            save_btn = Gtk.Button(icon_name="document-save-symbolic")
            save_btn.add_css_class("flat")
            save_btn.set_tooltip_text("Rename")
            save_btn.connect("clicked", lambda *_b, cid=cat.id, e=name_entry: self._rename_category_from_dialog(cid, e))
            row_box.append(save_btn)

            up_btn = Gtk.Button(icon_name="go-up-symbolic")
            up_btn.add_css_class("flat")
            up_btn.set_tooltip_text("Move Up")
            up_btn.set_sensitive(idx > 0)
            up_btn.connect("clicked", lambda *_b, cid=cat.id: self._move_category(cid, -1))
            row_box.append(up_btn)

            down_btn = Gtk.Button(icon_name="go-down-symbolic")
            down_btn.add_css_class("flat")
            down_btn.set_tooltip_text("Move Down")
            down_btn.set_sensitive(idx < len(categories) - 1)
            down_btn.connect("clicked", lambda *_b, cid=cat.id: self._move_category(cid, 1))
            row_box.append(down_btn)

            delete_btn = Gtk.Button(icon_name="user-trash-symbolic")
            delete_btn.add_css_class("flat")
            delete_btn.add_css_class("error")
            delete_btn.set_tooltip_text("Delete")
            delete_btn.connect("clicked", lambda *_b, cid=cat.id, name=cat.name: self._delete_category_from_dialog(cid, name))
            row_box.append(delete_btn)

            row.set_child(row_box)
            self._enable_category_drag(row)
            self._cat_dialog_list.append(row)

    # ── Category drag and drop ────────────────────────────────────────────

    def _enable_category_drag(self, row):
        """
        Make one category row draggable onto another to reorder it.

        The up/down buttons stay: drag and drop is the native GTK4 gesture,
        but it is not discoverable on its own and is awkward with a long list.
        """
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect("prepare", self._on_category_drag_prepare, row)
        row.add_controller(source)

        target = Gtk.DropTarget.new(GObject.TYPE_INT, Gdk.DragAction.MOVE)
        target.connect("drop", self._on_category_drop, row)
        row.add_controller(target)

    @staticmethod
    def _on_category_drag_prepare(_source, _x, _y, row):
        # The payload is the dragged row's category id.
        return Gdk.ContentProvider.new_for_value(row.category_id)

    def _on_category_drop(self, _target, value, _x, _y, target_row):
        dragged_id = int(value)
        target_id = target_row.category_id
        if dragged_id == target_id:
            return False

        ordered = [c.id for c in self._db.get_categories()]
        if dragged_id not in ordered or target_id not in ordered:
            return False

        ordered.remove(dragged_id)
        ordered.insert(ordered.index(target_id), dragged_id)

        try:
            self._db.reorder_categories(ordered)
        except Exception as exc:
            self._set_cat_dialog_status(f"Could not reorder categories: {exc}")
            return False

        self._set_cat_dialog_status("Reordered categories.")
        self.reload()
        self._refresh_category_manager_list()
        return True

    def _rename_category_from_dialog(self, category_id, entry: Gtk.Entry):
        name = entry.get_text().strip()
        if not name:
            self._set_cat_dialog_status("Category name is required.")
            return
        try:
            self._db.update_category_name(category_id, name)
            self._set_cat_dialog_status(f"Renamed category to '{name}'.")
            self.reload()
            self._refresh_category_manager_list()
        except Exception as e:
            self._set_cat_dialog_status(f"Failed to rename category: {e}")

    def _move_category(self, category_id, direction: int):
        categories = self._db.get_categories()
        ids = [c.id for c in categories]
        if category_id not in ids:
            return
        idx = ids.index(category_id)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(ids):
            return
        ids[idx], ids[new_idx] = ids[new_idx], ids[idx]
        self._db.reorder_categories(ids)
        self._set_cat_dialog_status("Updated category order.")
        self.reload()
        self._refresh_category_manager_list()

    def _delete_category_from_dialog(self, category_id, category_name: str):
        try:
            self._db.delete_category(category_id)
            if self._presenter.category_id == category_id:
                # Fall back to All rather than leave the view on a category
                # that no longer exists.
                self._presenter.set_category(None)
                self._sync_controls_from_prefs()
            self._set_cat_dialog_status(f"Deleted category '{category_name}'.")
            self.reload()
            self._refresh_category_manager_list()
        except Exception as e:
            self._set_cat_dialog_status(f"Failed to delete '{category_name}': {e}")

    def _set_cat_dialog_status(self, message: str):
        if hasattr(self, "_cat_dialog_status"):
            self._cat_dialog_status.set_text(message)

    def _set_info(self, text: str):
        self._info_label.set_text(text)

    def update_manga(self, manga: Manga):
        """Update a specific manga card (e.g. after adding to library)."""
        self._presenter.update_manga(manga)
