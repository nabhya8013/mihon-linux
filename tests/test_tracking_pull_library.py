"""
TrackManager.pull_library(): the pull that runs after a scheduled library
update. It must refresh tracked library manga from logged-in services and
count only real changes.
"""
import unittest

from mihon.core.tracking.base import TrackerError
from mihon.core.tracking.manager import TrackManager
from tests.test_tracking_manager import FakeService, _fresh_db


class PullLibraryTests(unittest.TestCase):
    def setUp(self):
        from mihon.core.models import Manga
        self.db = _fresh_db()
        self.Manga = Manga
        self.lib_id = self.db.upsert_manga(Manga(source_id="s", source_manga_id="a", title="A", in_library=True))
        self.service = FakeService()
        self.manager = TrackManager(self.db, services=[self.service])
        self.manager.link(self.lib_id, "fake", "42")

    def test_changed_remote_progress_is_pulled_and_counted(self):
        result = self.manager.pull_library()
        self.assertEqual((result.checked, result.changed), (1, 1))
        self.assertEqual(self.manager.entry_for(self.lib_id, "fake").progress, 55.0)

    def test_unchanged_entry_is_checked_but_not_counted(self):
        self.manager.pull_library()
        result = self.manager.pull_library()
        self.assertEqual((result.checked, result.changed), (1, 0))

    def test_manga_outside_the_library_is_skipped(self):
        other = self.db.upsert_manga(self.Manga(source_id="s", source_manga_id="b", title="B", in_library=False))
        self.manager.link(other, "fake", "43")
        self.service.refreshes.clear()
        self.manager.pull_library()
        self.assertEqual(len(self.service.refreshes), 1)

    def test_nothing_happens_when_logged_out(self):
        manager = TrackManager(self.db, services=[FakeService(logged_in=False)])
        result = manager.pull_library()
        self.assertEqual((result.checked, result.changed), (0, 0))

    def test_failed_refresh_keeps_local_entry(self):
        def boom(entry):
            raise TrackerError("offline")
        self.service.refresh = boom
        result = self.manager.pull_library()
        self.assertEqual((result.checked, result.changed), (1, 0))
        self.assertEqual(self.manager.entry_for(self.lib_id, "fake").progress, 0.0)

    def test_tracked_library_ids_query(self):
        self.assertEqual(self.db.get_tracked_library_manga_ids(), [self.lib_id])


if __name__ == "__main__":
    unittest.main()
