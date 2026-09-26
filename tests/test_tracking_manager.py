"""
Tests for TrackManager and the persistent retry queue.

These run against a real SQLite database in a temporary XDG_DATA_HOME, so the
schema migration and the queue table are exercised as shipped.
"""
import os
import tempfile
import time
import unittest

os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())

from mihon.core.tracking.base import (
    STATUS_COMPLETED,
    STATUS_READING,
    TrackEntry,
    TrackerAuthError,
    TrackerError,
    TrackerService,
)
from mihon.core.tracking.manager import TrackManager
from mihon.core.tracking.queue import MAX_ATTEMPTS, TrackingQueue


class FakeCredentials:
    def __init__(self, tokens=None):
        self._tokens = tokens or {}

    def get_token(self, provider):
        return self._tokens.get(provider)

    def set_token(self, provider, token):
        self._tokens[provider] = token

    def clear(self, provider):
        self._tokens.pop(provider, None)


class FakeService(TrackerService):
    id = "fake"
    name = "Fake Tracker"

    def __init__(self, logged_in=True, fail_with=None):
        super().__init__(FakeCredentials({"fake": "token"} if logged_in else {}))
        self.fail_with = fail_with
        self.updates = []
        self.refreshes = []
        self.unbound = []
        self.remote = TrackEntry(
            provider="fake", remote_id="42", library_id="7",
            title="Remote Title", status=STATUS_READING,
            progress=0.0, total_chapters=100.0,
        )

    def authorization_url(self):
        return "https://example.invalid/auth"

    def complete_login(self, redirect_response):
        return True

    def search(self, query):
        return []

    def bind(self, remote_id):
        return TrackEntry(**self.remote.__dict__)

    def update(self, entry):
        if self.fail_with:
            raise self.fail_with
        self.updates.append(entry)
        result = TrackEntry(**entry.__dict__)
        result.library_id = "7"
        return result

    def refresh(self, entry):
        self.refreshes.append(entry)
        result = TrackEntry(**self.remote.__dict__)
        result.progress = 55.0
        return result

    def unbind(self, entry):
        self.unbound.append(entry)


def _fresh_db():
    """A brand-new database in its own directory."""
    import importlib
    from pathlib import Path

    tmp = tempfile.mkdtemp()
    os.environ["XDG_DATA_HOME"] = tmp
    from mihon.core import database
    importlib.reload(database)
    db = database.Database()
    return db


class TrackManagerTests(unittest.TestCase):

    def setUp(self):
        from mihon.core.models import Manga
        self.db = _fresh_db()
        self.manga_id = self.db.upsert_manga(
            Manga(source_id="s", source_manga_id="m1", title="Local Title", in_library=True)
        )
        self.service = FakeService()
        self.manager = TrackManager(self.db, services=[self.service])

    # ── Linking ───────────────────────────────────────────────────────────

    def test_link_stores_the_remote_entry(self):
        entry = self.manager.link(self.manga_id, "fake", "42")
        self.assertEqual(entry.remote_id, "42")
        stored = self.manager.entry_for(self.manga_id, "fake")
        self.assertEqual(stored.title, "Remote Title")
        self.assertEqual(stored.total_chapters, 100.0)

    def test_linking_an_unknown_service_raises(self):
        with self.assertRaises(TrackerError):
            self.manager.link(self.manga_id, "nope", "1")

    def test_unlink_removes_the_local_row(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.manager.unlink(self.manga_id, "fake")
        self.assertEqual(self.manager.entries_for(self.manga_id), [])

    def test_unlink_leaves_the_remote_entry_alone_by_default(self):
        """An accidental unlink must not wipe the user's tracker list entry."""
        self.manager.link(self.manga_id, "fake", "42")
        self.manager.unlink(self.manga_id, "fake")
        self.assertEqual(self.service.unbound, [])

    def test_unlink_can_delete_remotely_when_asked(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.manager.unlink(self.manga_id, "fake", remote=True)
        self.assertEqual(len(self.service.unbound), 1)

    # ── Progress ──────────────────────────────────────────────────────────

    def test_sync_progress_pushes_to_the_service(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.manager.sync_progress(self.manga_id, 12)
        self.assertEqual(self.service.updates[-1].progress, 12.0)

    def test_sync_progress_stores_the_result_locally(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.manager.sync_progress(self.manga_id, 12)
        self.assertEqual(self.manager.entry_for(self.manga_id, "fake").progress, 12.0)

    def test_rereading_an_earlier_chapter_sends_nothing(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.manager.sync_progress(self.manga_id, 30)
        self.service.updates.clear()
        self.manager.sync_progress(self.manga_id, 5)
        self.assertEqual(self.service.updates, [])

    def test_finishing_the_last_chapter_completes_the_entry(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.manager.sync_progress(self.manga_id, 100)
        self.assertEqual(
            self.manager.entry_for(self.manga_id, "fake").status, STATUS_COMPLETED
        )

    def test_syncing_an_untracked_manga_does_nothing(self):
        self.assertEqual(self.manager.sync_progress(self.manga_id, 5), [])

    # ── Failure handling ──────────────────────────────────────────────────

    def test_a_network_failure_queues_the_update(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.service.fail_with = TrackerError("offline")
        self.manager.sync_progress(self.manga_id, 12)
        self.assertEqual(self.manager.queue.count(), 1)

    def test_local_progress_advances_even_when_the_push_fails(self):
        """The app's own view of progress must not depend on the network."""
        self.manager.link(self.manga_id, "fake", "42")
        self.service.fail_with = TrackerError("offline")
        self.manager.sync_progress(self.manga_id, 12)
        self.assertEqual(self.manager.entry_for(self.manga_id, "fake").progress, 12.0)

    def test_an_auth_failure_is_not_queued(self):
        """Retrying cannot help until the user logs in again."""
        self.manager.link(self.manga_id, "fake", "42")
        self.service.fail_with = TrackerAuthError("token revoked")
        self.manager.sync_progress(self.manga_id, 12)
        self.assertEqual(self.manager.queue.count(), 0)

    def test_a_logged_out_service_is_skipped(self):
        service = FakeService(logged_in=False)
        manager = TrackManager(self.db, services=[service])
        manager.save_entry(self.manga_id, TrackEntry(provider="fake", remote_id="42"))
        manager.sync_progress(self.manga_id, 5)
        self.assertEqual(service.updates, [])

    # ── Queue draining ────────────────────────────────────────────────────

    def test_process_queue_delivers_a_queued_update(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.service.fail_with = TrackerError("offline")
        self.manager.sync_progress(self.manga_id, 12)

        self.service.fail_with = None
        self.assertEqual(self.manager.process_queue(), 1)
        self.assertEqual(self.manager.queue.count(), 0)

    def test_a_still_failing_update_stays_queued_with_backoff(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.service.fail_with = TrackerError("offline")
        self.manager.sync_progress(self.manga_id, 12)

        self.assertEqual(self.manager.process_queue(), 0)
        queued = self.manager.queue.all()[0]
        self.assertEqual(queued.attempts, 1)
        self.assertGreater(queued.next_attempt_at, time.time())

    def test_an_update_not_yet_due_is_left_alone(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.service.fail_with = TrackerError("offline")
        self.manager.sync_progress(self.manga_id, 12)
        self.manager.process_queue()

        self.service.fail_with = None
        self.assertEqual(self.manager.process_queue(), 0)

    def test_an_auth_failure_drops_the_queued_update(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.service.fail_with = TrackerError("offline")
        self.manager.sync_progress(self.manga_id, 12)

        self.service.fail_with = TrackerAuthError("logged out")
        self.manager.process_queue()
        self.assertEqual(self.manager.queue.count(), 0)

    # ── Pull sync ─────────────────────────────────────────────────────────

    def test_pull_brings_remote_state_back(self):
        self.manager.link(self.manga_id, "fake", "42")
        self.manager.pull(self.manga_id)
        self.assertEqual(self.manager.entry_for(self.manga_id, "fake").progress, 55.0)

    def test_a_failing_pull_keeps_the_local_entry(self):
        self.manager.link(self.manga_id, "fake", "42")

        def boom(_entry):
            raise TrackerError("offline")

        self.service.refresh = boom
        entries = self.manager.pull(self.manga_id)
        self.assertEqual(len(entries), 1)


class TrackingQueueTests(unittest.TestCase):

    def setUp(self):
        from mihon.core.models import Manga
        self.db = _fresh_db()
        self.manga_id = self.db.upsert_manga(
            Manga(source_id="s", source_manga_id="m1", title="T", in_library=True)
        )
        self.queue = TrackingQueue(self.db)

    def test_enqueue_then_read_back(self):
        self.queue.enqueue(self.manga_id, "fake", {"progress": 5})
        due = self.queue.due()
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].payload["progress"], 5)

    def test_enqueue_replaces_a_pending_update_for_the_same_manga(self):
        """Only the newest progress matters; stale entries must not pile up."""
        self.queue.enqueue(self.manga_id, "fake", {"progress": 5})
        self.queue.enqueue(self.manga_id, "fake", {"progress": 9})
        self.assertEqual(self.queue.count(), 1)
        self.assertEqual(self.queue.due()[0].payload["progress"], 9)

    def test_different_providers_queue_separately(self):
        self.queue.enqueue(self.manga_id, "a", {"progress": 1})
        self.queue.enqueue(self.manga_id, "b", {"progress": 1})
        self.assertEqual(self.queue.count(), 2)

    def test_mark_failed_schedules_a_later_attempt(self):
        queued_id = self.queue.enqueue(self.manga_id, "fake", {})
        self.assertTrue(self.queue.mark_failed(queued_id, "offline"))
        self.assertEqual(self.queue.due(), [])

    def test_an_entry_is_dropped_after_too_many_attempts(self):
        queued_id = self.queue.enqueue(self.manga_id, "fake", {})
        for _ in range(MAX_ATTEMPTS - 1):
            self.assertTrue(self.queue.mark_failed(queued_id, "offline"))
        self.assertFalse(self.queue.mark_failed(queued_id, "offline"))
        self.assertEqual(self.queue.count(), 0)

    def test_mark_failed_on_a_missing_entry_is_harmless(self):
        self.assertFalse(self.queue.mark_failed(9999, "gone"))

    def test_clear_narrowed_to_one_provider(self):
        self.queue.enqueue(self.manga_id, "a", {})
        self.queue.enqueue(self.manga_id, "b", {})
        self.queue.clear(manga_id=self.manga_id, provider="a")
        self.assertEqual(self.queue.count(), 1)

    def test_clear_everything(self):
        self.queue.enqueue(self.manga_id, "a", {})
        self.queue.clear()
        self.assertEqual(self.queue.count(), 0)

    def test_a_malformed_payload_reads_back_as_empty(self):
        self.queue.enqueue(self.manga_id, "fake", {})
        self.db.conn.execute("UPDATE tracking_queue SET payload='not json'")
        self.db.conn.commit()
        self.assertEqual(self.queue.due()[0].payload, {})

    def test_deleting_a_manga_removes_its_queued_updates(self):
        """The foreign key must cascade, or the queue leaks rows forever."""
        self.queue.enqueue(self.manga_id, "fake", {})
        self.db.conn.execute("DELETE FROM manga WHERE id=?", (self.manga_id,))
        self.db.conn.commit()
        self.assertEqual(self.queue.count(), 0)


if __name__ == "__main__":
    unittest.main()
