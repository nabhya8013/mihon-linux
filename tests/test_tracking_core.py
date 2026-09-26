"""
Tests for the tracking contract, credential storage and retry queue.

Nothing here touches the network: the services are exercised through fake
sessions, and the credential store through a fake keyring.
"""
import json
import time
import unittest

from mihon.core.tracking.base import (
    ALL_STATUSES,
    STATUS_COMPLETED,
    STATUS_PLAN_TO_READ,
    STATUS_READING,
    TrackEntry,
)
from mihon.core.tracking.credentials import SETTING_PREFIX, CredentialStore, Token
from mihon.core.tracking.manager import READ_THRESHOLD, TrackManager
from mihon.core.tracking.queue import (
    BASE_BACKOFF_SECONDS,
    MAX_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
    backoff_for,
)


class FakeSettingsDB:
    def __init__(self):
        self.settings = {}

    def get_setting(self, key, default=""):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value


class FakeSecretModule:
    """Stand-in for gi.repository.Secret with an in-memory store."""

    class SchemaFlags:
        NONE = 0

    class SchemaAttributeType:
        STRING = 0

    COLLECTION_DEFAULT = "default"

    def __init__(self, failing=False):
        self.store = {}
        self.failing = failing

    class Schema:
        @staticmethod
        def new(name, flags, attributes):
            return {"name": name}

    def password_store_sync(self, schema, attrs, collection, label, secret, cancellable):
        if self.failing:
            raise RuntimeError("keyring locked")
        self.store[attrs["provider"]] = secret

    def password_lookup_sync(self, schema, attrs, cancellable):
        if self.failing:
            raise RuntimeError("keyring locked")
        return self.store.get(attrs["provider"])

    def password_clear_sync(self, schema, attrs, cancellable):
        self.store.pop(attrs["provider"], None)


class TokenTests(unittest.TestCase):

    def test_round_trip(self):
        token = Token("abc", "refresh", 123.0)
        restored = Token.from_json(token.to_json())
        self.assertEqual(restored.access_token, "abc")
        self.assertEqual(restored.refresh_token, "refresh")

    def test_empty_and_malformed_json(self):
        self.assertIsNone(Token.from_json(""))
        self.assertIsNone(Token.from_json("not json"))
        self.assertIsNone(Token.from_json(json.dumps({"access_token": ""})))

    def test_a_token_with_no_expiry_never_expires(self):
        self.assertFalse(Token("abc").is_expired)

    def test_an_elapsed_expiry_is_expired(self):
        self.assertTrue(Token("abc", expires_at=time.time() - 10).is_expired)

    def test_a_token_expiring_within_the_minute_counts_as_expired(self):
        """Otherwise a request can start with a token that dies mid-flight."""
        self.assertTrue(Token("abc", expires_at=time.time() + 30).is_expired)

    def test_a_token_valid_for_an_hour_is_not_expired(self):
        self.assertFalse(Token("abc", expires_at=time.time() + 3600).is_expired)


class CredentialStoreTests(unittest.TestCase):

    def test_keyring_is_used_when_available(self):
        secret = FakeSecretModule()
        db = FakeSettingsDB()
        store = CredentialStore(db, secret_module=secret)

        self.assertTrue(store.uses_keyring)
        store.set_token("anilist", Token("secret-value"))
        self.assertIn("anilist", secret.store)

    def test_a_token_never_lands_in_the_database_when_a_keyring_exists(self):
        secret = FakeSecretModule()
        db = FakeSettingsDB()
        CredentialStore(db, secret_module=secret).set_token("anilist", Token("secret-value"))
        self.assertEqual(db.settings.get(SETTING_PREFIX + "anilist", ""), "")

    def test_round_trip_through_the_keyring(self):
        store = CredentialStore(FakeSettingsDB(), secret_module=FakeSecretModule())
        store.set_token("anilist", Token("abc"))
        store._cache.clear()
        self.assertEqual(store.get_token("anilist").access_token, "abc")

    def test_fallback_to_the_database_when_no_keyring_exists(self):
        db = FakeSettingsDB()
        store = CredentialStore(db, force_fallback=True)
        self.assertFalse(store.uses_keyring)
        store.set_token("anilist", Token("abc"))
        self.assertTrue(db.settings[SETTING_PREFIX + "anilist"])
        store._cache.clear()
        self.assertEqual(store.get_token("anilist").access_token, "abc")

    def test_a_failing_keyring_falls_back_instead_of_raising(self):
        db = FakeSettingsDB()
        store = CredentialStore(db, secret_module=FakeSecretModule(failing=True))
        store.set_token("anilist", Token("abc"))
        store._cache.clear()
        self.assertEqual(store.get_token("anilist").access_token, "abc")

    def test_missing_token_is_none(self):
        store = CredentialStore(FakeSettingsDB(), force_fallback=True)
        self.assertIsNone(store.get_token("anilist"))

    def test_clear_removes_from_both_backends(self):
        secret = FakeSecretModule()
        db = FakeSettingsDB()
        store = CredentialStore(db, secret_module=secret)
        store.set_token("anilist", Token("abc"))
        store.clear("anilist")
        self.assertNotIn("anilist", secret.store)
        self.assertEqual(db.settings.get(SETTING_PREFIX + "anilist", ""), "")
        self.assertIsNone(store.get_token("anilist"))

    def test_setting_an_empty_token_clears_instead(self):
        store = CredentialStore(FakeSettingsDB(), force_fallback=True)
        store.set_token("anilist", Token("abc"))
        store.set_token("anilist", None)
        self.assertIsNone(store.get_token("anilist"))

    def test_backend_name_reports_the_unencrypted_fallback(self):
        store = CredentialStore(FakeSettingsDB(), force_fallback=True)
        self.assertIn("not encrypted", store.backend_name)


class TrackEntryTests(unittest.TestCase):

    def test_progress_advances(self):
        entry = TrackEntry(progress=3.0)
        self.assertEqual(entry.with_progress(7).progress, 7.0)

    def test_progress_never_moves_backwards(self):
        """Rereading an earlier chapter must not erase real progress."""
        entry = TrackEntry(progress=40.0)
        self.assertEqual(entry.with_progress(2).progress, 40.0)

    def test_reaching_the_last_chapter_completes_the_entry(self):
        entry = TrackEntry(progress=98.0, total_chapters=100.0, status=STATUS_READING)
        self.assertEqual(entry.with_progress(100).status, STATUS_COMPLETED)

    def test_no_completion_when_the_total_is_unknown(self):
        entry = TrackEntry(progress=98.0, total_chapters=0.0, status=STATUS_READING)
        self.assertEqual(entry.with_progress(100).status, STATUS_READING)

    def test_reading_something_planned_moves_it_to_reading(self):
        entry = TrackEntry(progress=0.0, status=STATUS_PLAN_TO_READ)
        self.assertEqual(entry.with_progress(1).status, STATUS_READING)

    def test_with_progress_does_not_mutate_the_original(self):
        entry = TrackEntry(progress=3.0)
        entry.with_progress(9)
        self.assertEqual(entry.progress, 3.0)

    def test_every_status_has_a_label(self):
        from mihon.core.tracking.base import STATUS_LABELS
        for status in ALL_STATUSES:
            self.assertIn(status, STATUS_LABELS)


class ReadThresholdTests(unittest.TestCase):

    def test_the_last_page_counts(self):
        self.assertTrue(TrackManager.should_sync(19, 20))

    def test_the_first_page_does_not(self):
        self.assertFalse(TrackManager.should_sync(0, 20))

    def test_the_threshold_boundary(self):
        # 17 of 20 pages is exactly 85%.
        self.assertTrue(TrackManager.should_sync(16, 20))
        self.assertFalse(TrackManager.should_sync(15, 20))

    def test_a_one_page_chapter_counts_immediately(self):
        self.assertTrue(TrackManager.should_sync(0, 1))

    def test_an_empty_chapter_never_counts(self):
        self.assertFalse(TrackManager.should_sync(0, 0))

    def test_the_threshold_is_configurable(self):
        self.assertTrue(TrackManager.should_sync(9, 20, threshold=0.5))

    def test_the_default_threshold_matches_android(self):
        self.assertAlmostEqual(READ_THRESHOLD, 0.85)


class BackoffTests(unittest.TestCase):

    def test_the_first_retry_uses_the_base_delay(self):
        self.assertEqual(backoff_for(1), BASE_BACKOFF_SECONDS)

    def test_the_delay_doubles(self):
        self.assertEqual(backoff_for(2), BASE_BACKOFF_SECONDS * 2)
        self.assertEqual(backoff_for(3), BASE_BACKOFF_SECONDS * 4)

    def test_the_delay_is_capped(self):
        self.assertEqual(backoff_for(50), MAX_BACKOFF_SECONDS)

    def test_no_delay_before_the_first_attempt(self):
        self.assertEqual(backoff_for(0), 0.0)

    def test_the_cap_is_reached_before_attempts_run_out(self):
        """Otherwise the cap would never actually apply."""
        self.assertLessEqual(backoff_for(MAX_ATTEMPTS), MAX_BACKOFF_SECONDS)


if __name__ == "__main__":
    unittest.main()
