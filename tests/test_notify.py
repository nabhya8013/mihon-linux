"""Tests for toast-based error surfacing."""
import unittest

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

Gtk.init_check()
Adw.init()

from mihon.ui.notify import find_toast_overlay, notify, notify_error, notify_retry


class NotifyTests(unittest.TestCase):

    def _window_with_overlay(self):
        window = Adw.ApplicationWindow()
        overlay = Adw.ToastOverlay()
        child = Gtk.Box()
        overlay.set_child(child)
        window.set_content(overlay)
        # This is how MainWindow exposes it.
        window.toast_overlay = overlay
        return window, overlay, child

    def test_finds_the_overlay_from_a_descendant(self):
        window, overlay, child = self._window_with_overlay()
        self.assertIs(find_toast_overlay(child), overlay)

    def test_finds_the_overlay_by_walking_parents(self):
        overlay = Adw.ToastOverlay()
        child = Gtk.Box()
        overlay.set_child(child)
        self.assertIs(find_toast_overlay(child), overlay)

    def test_no_overlay_returns_none(self):
        self.assertIsNone(find_toast_overlay(Gtk.Box()))
        self.assertIsNone(find_toast_overlay(None))

    def test_notify_shows_a_toast_when_an_overlay_exists(self):
        _window, _overlay, child = self._window_with_overlay()
        self.assertTrue(notify(child, "Something happened"))

    def test_notify_without_an_overlay_logs_and_returns_false(self):
        with self.assertLogs("notify", level="INFO"):
            self.assertFalse(notify(Gtk.Box(), "Nowhere to show this"))

    def test_an_error_is_logged_at_error_level(self):
        with self.assertLogs("notify", level="ERROR") as captured:
            notify_error(Gtk.Box(), "It broke")
        self.assertIn("It broke", captured.output[0])

    def test_an_empty_message_shows_nothing(self):
        _window, _overlay, child = self._window_with_overlay()
        self.assertFalse(notify(child, ""))

    def test_a_retry_toast_carries_its_callback(self):
        _window, _overlay, child = self._window_with_overlay()
        called = []
        self.assertTrue(notify_retry(child, "Failed", lambda: called.append(1)))

    def test_notify_never_raises_without_a_window(self):
        # A widget built in a test, or before it is added to a window.
        notify(Gtk.Label(), "orphaned")
        notify_error(None, "no widget at all")


if __name__ == "__main__":
    unittest.main()
