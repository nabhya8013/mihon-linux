"""
Tests for app.py's sync_tracking_queue(), which drains the tracker retry
queue at startup - before any window exists, so notify_desktop_for_app() is
the only way its result ever reaches the user.

get_track_manager() is imported lazily inside the function
(`from .core.tracking import get_track_manager`), so the patch target is the
real source (mihon.core.tracking.get_track_manager), not a name on
mihon.app - that import statement resolves it fresh on each call.
"""
import unittest
from unittest.mock import MagicMock, patch

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

Gtk.init_check()
Adw.init()

from mihon import app as app_module


def _manager(pending_before, delivered, pending_after):
    manager = MagicMock()
    manager.queue.count.side_effect = [pending_before, pending_after]
    manager.process_queue.return_value = delivered
    return manager


class SyncTrackingQueueTests(unittest.TestCase):

    def test_empty_queue_does_nothing(self):
        manager = _manager(pending_before=0, delivered=0, pending_after=0)
        with patch("mihon.core.tracking.get_track_manager", return_value=manager):
            with patch("mihon.app.notify_desktop_for_app") as notify:
                app_module.sync_tracking_queue(app=object())
        manager.process_queue.assert_not_called()
        notify.assert_not_called()

    def test_all_delivered_notifies_success(self):
        manager = _manager(pending_before=3, delivered=3, pending_after=0)
        with patch("mihon.core.tracking.get_track_manager", return_value=manager):
            with patch("mihon.app.notify_desktop_for_app") as notify:
                app_module.sync_tracking_queue(app="fake-app")
        notify.assert_called_once()
        args, kwargs = notify.call_args
        self.assertEqual(args[0], "fake-app")
        self.assertEqual(args[1], "Tracker sync")
        self.assertIn("3", args[2])
        self.assertNotIn("waiting", args[2])
        self.assertEqual(kwargs["notification_id"], "tracking-queue")

    def test_partial_delivery_mentions_what_is_still_stuck(self):
        manager = _manager(pending_before=3, delivered=2, pending_after=1)
        with patch("mihon.core.tracking.get_track_manager", return_value=manager):
            with patch("mihon.app.notify_desktop_for_app") as notify:
                app_module.sync_tracking_queue(app="fake-app")
        body = notify.call_args.args[2]
        self.assertIn("2", body)
        self.assertIn("1 still waiting", body)

    def test_total_failure_notifies_failure_not_success(self):
        manager = _manager(pending_before=2, delivered=0, pending_after=2)
        with patch("mihon.core.tracking.get_track_manager", return_value=manager):
            with patch("mihon.app.notify_desktop_for_app") as notify:
                app_module.sync_tracking_queue(app="fake-app")
        args, kwargs = notify.call_args
        self.assertEqual(args[1], "Tracker sync failed")
        self.assertIn("2", args[2])


if __name__ == "__main__":
    unittest.main()
