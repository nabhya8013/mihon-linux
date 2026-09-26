"""Tests for the System/Light/Dark appearance theme mapping."""
import unittest
from unittest.mock import patch

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

Gtk.init_check()
Adw.init()

from mihon.ui.theme import THEME_VALUES, apply_appearance_theme


class _FakeDB:
    def __init__(self, theme="dark"):
        self._theme = theme

    def get_setting(self, key, default=""):
        if key == "appearance_theme":
            return self._theme
        return default


class ThemeTests(unittest.TestCase):

    def _apply_and_read(self, theme):
        with patch("mihon.ui.theme.get_db", return_value=_FakeDB(theme)):
            apply_appearance_theme()
        return Adw.StyleManager.get_default().get_color_scheme()

    def test_system_maps_to_default(self):
        self.assertEqual(self._apply_and_read("system"), Adw.ColorScheme.DEFAULT)

    def test_light_maps_to_force_light(self):
        self.assertEqual(self._apply_and_read("light"), Adw.ColorScheme.FORCE_LIGHT)

    def test_dark_maps_to_force_dark(self):
        self.assertEqual(self._apply_and_read("dark"), Adw.ColorScheme.FORCE_DARK)

    def test_unknown_value_falls_back_to_dark(self):
        self.assertEqual(self._apply_and_read("nonsense"), Adw.ColorScheme.FORCE_DARK)

    def test_theme_values_list_matches_the_settings_ui_order(self):
        self.assertEqual(THEME_VALUES, ["system", "light", "dark"])


if __name__ == "__main__":
    unittest.main()
