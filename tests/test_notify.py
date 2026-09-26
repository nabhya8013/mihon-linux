"""Tests for toast-based and desktop notification surfacing."""
import unittest
from unittest.mock import patch

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

Gtk.init_check()
Adw.init()

from mihon.ui.notify import (
    find_toast_overlay,
    notify,
    notify_desktop,
    notify_error,
    notify_retry,
)


class _FakeApp:
    def __init__(self):
        self.sent = []

    def send_notification(self, notification_id, notification):
        self.sent.append((notification_id, notification))


class _FakeRoot:
    def __init__(self, app):
        self._app = app

    def get_application(self):
        return self._app


class _FakeWidget:
    def __init__(self, root):
        self._root = root

    def get_root(self):
        return self._root


class _FakeSettingsDB:
    def __init__(self, enabled=True):
        self._enabled = "1" if enabled else "0"

    def get_setting(self, key, default=""):
        if key == "desktop_notifications_enabled":
            return self._enabled
        return default


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


class NotifyDesktopTests(unittest.TestCase):

    def test_sent_when_an_application_is_reachable(self):
        app = _FakeApp()
        widget = _FakeWidget(_FakeRoot(app))
        with patch("mihon.ui.notify.get_db", return_value=_FakeSettingsDB()):
            self.assertTrue(notify_desktop(widget, "Title", "Body", notification_id="x"))
        self.assertEqual(len(app.sent), 1)
        self.assertEqual(app.sent[0][0], "x")

    def test_no_application_logs_and_returns_false(self):
        with patch("mihon.ui.notify.get_db", return_value=_FakeSettingsDB()):
            with self.assertLogs("notify", level="INFO"):
                self.assertFalse(notify_desktop(Gtk.Box(), "Title"))

    def test_disabled_by_setting_sends_nothing(self):
        app = _FakeApp()
        widget = _FakeWidget(_FakeRoot(app))
        with patch("mihon.ui.notify.get_db", return_value=_FakeSettingsDB(enabled=False)):
            self.assertFalse(notify_desktop(widget, "Title"))
        self.assertEqual(app.sent, [])

    def test_never_raises_without_a_window(self):
        with patch("mihon.ui.notify.get_db", return_value=_FakeSettingsDB()):
            notify_desktop(Gtk.Label(), "orphaned")
            notify_desktop(None, "no widget at all")


if __name__ == "__main__":
    unittest.main()
