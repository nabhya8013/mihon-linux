"""
Source filter UI.

Renders the ``FilterList`` a source exposes through ``Extension.get_filters()``
into real GTK widgets and reads the edited state back out in the same shape,
so the JVM bridge can reapply it positionally onto the source's own
``FilterList`` (see ``ExtensionHandler.applyFilterState``).

Supported filter types, matching ``eu.kanade.tachiyomi.source.model.Filter``:

===========  ==============================  ==================================
type         widget                          state written back
===========  ==============================  ==================================
header       dim label                       none
separator    horizontal rule                 none
select       ``Gtk.DropDown``                ``int`` index into ``values``
text         ``Gtk.Entry``                   ``str``
checkbox     ``Gtk.CheckButton``             ``bool``
tristate     cycling button                  ``int`` 0 ignore/1 include/2 exclude
group        framed box of child filters     ``list`` of child filter nodes
sort         ``Gtk.DropDown`` + direction     ``{"index": int, "ascending": bool}``
===========  ==============================  ==================================
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

# Filter.TriState states, mirroring the Android constants.
TRISTATE_IGNORE = 0
TRISTATE_INCLUDE = 1
TRISTATE_EXCLUDE = 2

_TRISTATE_LABELS = {
    TRISTATE_IGNORE: "",
    TRISTATE_INCLUDE: "✓",   # check
    TRISTATE_EXCLUDE: "✗",   # cross
}

_TRISTATE_TOOLTIPS = {
    TRISTATE_IGNORE: "Ignored",
    TRISTATE_INCLUDE: "Included",
    TRISTATE_EXCLUDE: "Excluded",
}


class _FilterBinding:
    """One rendered filter plus a callable that reads its current state."""

    def __init__(self, index, reader):
        self.index = index
        self._reader = reader

    def state(self):
        return self._reader()


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_values(spec):
    values = spec.get("values") or []
    return [str(v) for v in values]


class FilterListView(Gtk.Box):
    """
    A scrollable column of widgets built from a source's serialized filters.

    ``get_state()`` returns the list of dicts to hand to
    ``SearchFilter.source_filters``. Filters whose state cannot change
    (headers, separators) are omitted.
    """

    def __init__(self, filters):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_start(16)
        self.set_margin_end(16)
        self.set_margin_top(16)
        self.set_margin_bottom(16)

        self._filters = list(filters or [])
        self._bindings = []

        for spec in self._filters:
            widget, binding = self._build_filter(spec)
            if widget is not None:
                self.append(widget)
            if binding is not None:
                self._bindings.append(binding)

    # ── State ─────────────────────────────────────────────────────────────

    def get_state(self):
        """Current filter state, shaped for SearchFilter.source_filters."""
        return [
            {"index": binding.index, "state": binding.state()}
            for binding in self._bindings
        ]

    def has_editable_filters(self) -> bool:
        return bool(self._bindings)

    # ── Widget construction ───────────────────────────────────────────────

    def _build_filter(self, spec):
        """Return ``(widget, binding)`` for one filter dict."""
        if not isinstance(spec, dict):
            return None, None

        kind = str(spec.get("type") or "").lower()
        index = _as_int(spec.get("index"), -1)
        name = str(spec.get("name") or "")

        builder = {
            "header": self._build_header,
            "separator": self._build_separator,
            "select": self._build_select,
            "text": self._build_text,
            "checkbox": self._build_checkbox,
            "tristate": self._build_tristate,
            "sort": self._build_sort,
            "group": self._build_group,
        }.get(kind)

        if builder is None:
            # Unknown filter type — show the name so the user knows something
            # exists rather than silently dropping it.
            return self._build_header(spec, index, name)[0], None

        return builder(spec, index, name)

    def _build_header(self, spec, index, name):
        label = Gtk.Label(label=name, xalign=0.0)
        label.add_css_class("heading")
        label.set_wrap(True)
        return label, None

    def _build_separator(self, spec, index, name):
        return Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), None

    def _build_select(self, spec, index, name):
        values = _as_values(spec)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        label = Gtk.Label(label=name, xalign=0.0)
        label.set_hexpand(True)
        label.set_wrap(True)
        row.append(label)

        dropdown = Gtk.DropDown.new_from_strings(values or [""])
        selected = _as_int(spec.get("state"), 0)
        if 0 <= selected < max(len(values), 1):
            dropdown.set_selected(selected)
        row.append(dropdown)

        return row, _FilterBinding(index, lambda: int(dropdown.get_selected()))

    def _build_text(self, spec, index, name):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        label = Gtk.Label(label=name, xalign=0.0)
        label.add_css_class("dim-label")
        row.append(label)

        entry = Gtk.Entry()
        entry.set_text(str(spec.get("state") or ""))
        entry.set_hexpand(True)
        row.append(entry)

        return row, _FilterBinding(index, lambda: entry.get_text())

    def _build_checkbox(self, spec, index, name):
        check = Gtk.CheckButton(label=name)
        check.set_active(bool(spec.get("state")))
        return check, _FilterBinding(index, lambda: bool(check.get_active()))

    def _build_tristate(self, spec, index, name):
        """
        GTK has no native tri-state toggle, so use a small button that cycles
        ignore -> include -> exclude, the same order Android uses.
        """
        state = {"value": _as_int(spec.get("state"), TRISTATE_IGNORE) % 3}

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        button = Gtk.Button()
        button.set_size_request(32, -1)
        button.add_css_class("flat")

        label = Gtk.Label(label=name, xalign=0.0)
        label.set_hexpand(True)
        label.set_wrap(True)

        def refresh():
            button.set_label(_TRISTATE_LABELS[state["value"]])
            button.set_tooltip_text(
                f"{name}: {_TRISTATE_TOOLTIPS[state['value']]}"
            )

        def on_clicked(_button):
            state["value"] = (state["value"] + 1) % 3
            refresh()

        button.connect("clicked", on_clicked)
        refresh()

        row.append(button)
        row.append(label)

        return row, _FilterBinding(index, lambda: int(state["value"]))

    def _build_sort(self, spec, index, name):
        values = _as_values(spec)
        current = spec.get("state") or {}
        if not isinstance(current, dict):
            current = {}

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        label = Gtk.Label(label=name, xalign=0.0)
        label.add_css_class("dim-label")
        box.append(label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        dropdown = Gtk.DropDown.new_from_strings(values or [""])
        dropdown.set_hexpand(True)
        selected = _as_int(current.get("index"), 0)
        if 0 <= selected < max(len(values), 1):
            dropdown.set_selected(selected)
        row.append(dropdown)

        ascending = Gtk.ToggleButton()
        ascending.set_active(bool(current.get("ascending", True)))

        def refresh_direction(*_):
            if ascending.get_active():
                ascending.set_icon_name("view-sort-ascending-symbolic")
                ascending.set_tooltip_text("Ascending")
            else:
                ascending.set_icon_name("view-sort-descending-symbolic")
                ascending.set_tooltip_text("Descending")

        ascending.connect("toggled", refresh_direction)
        refresh_direction()
        row.append(ascending)

        box.append(row)

        def read():
            return {
                "index": int(dropdown.get_selected()),
                "ascending": bool(ascending.get_active()),
            }

        return box, _FilterBinding(index, read)

    def _build_group(self, spec, index, name):
        children = spec.get("state")
        if not isinstance(children, list):
            children = []

        frame = Gtk.Frame()
        frame.set_label(name or None)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        inner.set_margin_top(8)
        inner.set_margin_bottom(8)

        # A group's state is a positional list: every child needs a slot, even
        # the ones that carry no state, or the bridge would misalign them.
        child_readers = []
        for child_index, child in enumerate(children):
            if not isinstance(child, dict):
                child_readers.append(lambda idx=child_index: {"index": idx})
                continue

            child_widget, child_binding = self._build_filter(child)
            if child_widget is not None:
                inner.append(child_widget)

            if child_binding is None:
                child_readers.append(lambda idx=child_index: {"index": idx})
            else:
                child_readers.append(
                    lambda b=child_binding: {"index": b.index, "state": b.state()}
                )

        frame.set_child(inner)

        if not child_readers:
            return frame, None

        return frame, _FilterBinding(
            index, lambda: [reader() for reader in child_readers]
        )


class FilterDialog(Adw.Window):
    """Modal sheet that hosts a :class:`FilterListView` with Reset/Apply."""

    def __init__(self, parent, source_name: str, filters, on_apply):
        super().__init__(
            modal=True,
            transient_for=parent,
            title=f"{source_name} filters",
            default_width=420,
            default_height=560,
        )

        self._filters = filters
        self._on_apply = on_apply

        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_title_widget(Adw.WindowTitle(title="Filters", subtitle=source_name))

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel_btn)

        apply_btn = Gtk.Button(label="Apply")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._on_apply_clicked)
        header.pack_end(apply_btn)

        toolbar.add_top_bar(header)

        self._list_view = FilterListView(filters)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self._list_view)
        toolbar.set_content(scroll)

        reset_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reset_bar.set_margin_start(16)
        reset_bar.set_margin_end(16)
        reset_bar.set_margin_top(8)
        reset_bar.set_margin_bottom(8)

        reset_btn = Gtk.Button(label="Reset")
        reset_btn.set_hexpand(True)
        reset_btn.connect("clicked", self._on_reset_clicked)
        reset_bar.append(reset_btn)

        toolbar.add_bottom_bar(reset_bar)

        self.set_content(toolbar)

    def _on_apply_clicked(self, *_):
        state = self._list_view.get_state()
        self.close()
        if self._on_apply:
            self._on_apply(state)

    def _on_reset_clicked(self, *_):
        """Rebuild from the source's defaults and apply an empty state."""
        self.close()
        if self._on_apply:
            self._on_apply([])


__all__ = [
    "FilterListView",
    "FilterDialog",
    "TRISTATE_IGNORE",
    "TRISTATE_INCLUDE",
    "TRISTATE_EXCLUDE",
]
