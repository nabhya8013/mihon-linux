"""
Tests for the source filter UI state round-trip.

These exercise FilterListView directly: the widget tree is built without a
window, and get_state() must produce exactly the shape the JVM bridge's
applyFilterState() consumes.
"""
import unittest

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

Gtk.init_check()

from mihon.ui.filters import (
    FilterListView,
    TRISTATE_EXCLUDE,
    TRISTATE_IGNORE,
    TRISTATE_INCLUDE,
)


class FilterListViewTests(unittest.TestCase):

    def test_header_and_separator_carry_no_state(self):
        view = FilterListView([
            {"index": 0, "name": "Genres", "type": "header", "state": None},
            {"index": 1, "name": "", "type": "separator", "state": None},
        ])
        self.assertEqual(view.get_state(), [])
        self.assertFalse(view.has_editable_filters())

    def test_select_reports_default_and_edited_index(self):
        view = FilterListView([
            {
                "index": 3,
                "name": "Status",
                "type": "select",
                "values": ["Any", "Ongoing", "Completed"],
                "state": 1,
            },
        ])
        self.assertEqual(view.get_state(), [{"index": 3, "state": 1}])

        dropdown = self._find(view, Gtk.DropDown)
        dropdown.set_selected(2)
        self.assertEqual(view.get_state(), [{"index": 3, "state": 2}])

    def test_text_filter_round_trip(self):
        view = FilterListView([
            {"index": 0, "name": "Author", "type": "text", "state": "Oda"},
        ])
        self.assertEqual(view.get_state(), [{"index": 0, "state": "Oda"}])

        entry = self._find(view, Gtk.Entry)
        entry.set_text("Kishimoto")
        self.assertEqual(view.get_state(), [{"index": 0, "state": "Kishimoto"}])

    def test_checkbox_state_is_bool(self):
        view = FilterListView([
            {"index": 2, "name": "Completed only", "type": "checkbox", "state": False},
        ])
        self.assertEqual(view.get_state(), [{"index": 2, "state": False}])

        check = self._find(view, Gtk.CheckButton)
        check.set_active(True)
        state = view.get_state()
        self.assertEqual(state, [{"index": 2, "state": True}])
        self.assertIsInstance(state[0]["state"], bool)

    def test_tristate_cycles_ignore_include_exclude(self):
        view = FilterListView([
            {"index": 5, "name": "Action", "type": "tristate", "state": TRISTATE_IGNORE},
        ])
        self.assertEqual(view.get_state(), [{"index": 5, "state": TRISTATE_IGNORE}])

        button = self._find(view, Gtk.Button)
        button.emit("clicked")
        self.assertEqual(view.get_state(), [{"index": 5, "state": TRISTATE_INCLUDE}])
        button.emit("clicked")
        self.assertEqual(view.get_state(), [{"index": 5, "state": TRISTATE_EXCLUDE}])
        button.emit("clicked")
        self.assertEqual(view.get_state(), [{"index": 5, "state": TRISTATE_IGNORE}])

    def test_sort_state_is_index_and_direction(self):
        view = FilterListView([
            {
                "index": 1,
                "name": "Sort",
                "type": "sort",
                "values": ["Title", "Views", "Updated"],
                "state": {"index": 2, "ascending": False},
            },
        ])
        self.assertEqual(
            view.get_state(),
            [{"index": 1, "state": {"index": 2, "ascending": False}}],
        )

        dropdown = self._find(view, Gtk.DropDown)
        dropdown.set_selected(0)
        toggle = self._find(view, Gtk.ToggleButton)
        toggle.set_active(True)
        self.assertEqual(
            view.get_state(),
            [{"index": 1, "state": {"index": 0, "ascending": True}}],
        )

    def test_sort_with_null_state_defaults_to_first_ascending(self):
        view = FilterListView([
            {
                "index": 0,
                "name": "Sort",
                "type": "sort",
                "values": ["A", "B"],
                "state": None,
            },
        ])
        self.assertEqual(
            view.get_state(),
            [{"index": 0, "state": {"index": 0, "ascending": True}}],
        )

    def test_group_state_is_positional_child_list(self):
        view = FilterListView([
            {
                "index": 4,
                "name": "Genres",
                "type": "group",
                "state": [
                    {"index": 0, "name": "Action", "type": "tristate", "state": 0},
                    {"index": 1, "name": "Comedy", "type": "tristate", "state": 2},
                ],
            },
        ])
        self.assertEqual(
            view.get_state(),
            [{
                "index": 4,
                "state": [
                    {"index": 0, "state": 0},
                    {"index": 1, "state": 2},
                ],
            }],
        )

    def test_group_keeps_slots_for_stateless_children(self):
        """A child without state must still occupy its positional slot."""
        view = FilterListView([
            {
                "index": 0,
                "name": "Tags",
                "type": "group",
                "state": [
                    {"index": 0, "name": "Header", "type": "header", "state": None},
                    {"index": 1, "name": "Isekai", "type": "checkbox", "state": True},
                ],
            },
        ])
        state = view.get_state()[0]["state"]
        self.assertEqual(len(state), 2)
        self.assertEqual(state[0], {"index": 0})
        self.assertEqual(state[1], {"index": 1, "state": True})

    def test_unknown_filter_type_is_shown_but_carries_no_state(self):
        view = FilterListView([
            {"index": 0, "name": "Mystery widget", "type": "somethingnew", "state": 1},
        ])
        self.assertEqual(view.get_state(), [])

    def test_empty_filter_list(self):
        view = FilterListView([])
        self.assertEqual(view.get_state(), [])
        self.assertFalse(view.has_editable_filters())

    def test_non_dict_entries_are_ignored(self):
        view = FilterListView(["nonsense", None, 42])
        self.assertEqual(view.get_state(), [])

    # ── Helpers ───────────────────────────────────────────────────────────

    def _find(self, root, widget_type):
        """Depth-first search for the first widget of the given exact type."""
        found = self._find_all(root, widget_type)
        self.assertTrue(found, f"no {widget_type.__name__} in widget tree")
        return found[0]

    # Composite widgets own private children (a DropDown holds its own
    # ToggleButton and popover). Descending into them would return internals
    # that are not part of the filter UI, so stop at their boundary.
    _OPAQUE = (Gtk.DropDown, Gtk.Entry, Gtk.CheckButton, Gtk.Button)

    def _find_all(self, root, widget_type):
        results = []
        child = root.get_first_child()
        while child is not None:
            # Exact type, so Gtk.Button does not match Gtk.ToggleButton.
            if type(child) is widget_type:
                results.append(child)
            if not isinstance(child, self._OPAQUE):
                results.extend(self._find_all(child, widget_type))
            child = child.get_next_sibling()
        return results


if __name__ == "__main__":
    unittest.main()
