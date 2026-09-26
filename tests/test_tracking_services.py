"""
Tests for the AniList and MyAnimeList service implementations.

Both are driven through a fake session, so no request leaves the machine.
"""
import json
import time
import unittest

from mihon.core.tracking.anilist import AniListTracker
from mihon.core.tracking.base import (
    STATUS_COMPLETED,
    STATUS_PLAN_TO_READ,
    STATUS_READING,
    TrackEntry,
    TrackerAuthError,
    TrackerError,
)
from mihon.core.tracking.credentials import Token
from mihon.core.tracking.myanimelist import (
    MyAnimeListTracker,
    generate_code_verifier,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, content=b"x"):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.content = content

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses=None):
        # responses may be a single response or a list consumed in order.
        self._responses = responses if isinstance(responses, list) else [responses]
        self.calls = []

    def _next(self):
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._next()

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._next()


class FakeCredentials:
    def __init__(self, token=None):
        self.tokens = {}
        if token is not None:
            self.tokens["anilist"] = token
            self.tokens["myanimelist"] = token

    def get_token(self, provider):
        return self.tokens.get(provider)

    def set_token(self, provider, token):
        self.tokens[provider] = token

    def clear(self, provider):
        self.tokens.pop(provider, None)


class FakeDB:
    def __init__(self, settings=None):
        self.settings = dict(settings or {})

    def get_setting(self, key, default=""):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value


# ── AniList ───────────────────────────────────────────────────────────────

_ANILIST_MEDIA = {
    "id": 30002,
    "title": {"romaji": "Berserk", "english": "Berserk"},
    "coverImage": {"large": "https://img.invalid/cover.jpg"},
    "chapters": 374,
    "description": "A dark fantasy.",
    "status": "RELEASING",
    "startDate": {"year": 1989, "month": 8, "day": 25},
    "averageScore": 92,
    "siteUrl": "https://anilist.co/manga/30002",
}


class AniListTests(unittest.TestCase):

    def _tracker(self, responses, token="tok", client_id="123"):
        db = FakeDB({"tracker_anilist_client_id": client_id})
        return AniListTracker(
            FakeCredentials(Token(token) if token else None),
            db=db,
            session=FakeSession(responses),
        )

    def test_authorization_url_uses_the_implicit_grant(self):
        tracker = self._tracker(FakeResponse())
        url = tracker.authorization_url()
        self.assertIn("response_type=token", url)
        self.assertIn("client_id=123", url)

    def test_authorization_url_requires_a_client_id(self):
        tracker = self._tracker(FakeResponse(), client_id="")
        with self.assertRaises(TrackerError):
            tracker.authorization_url()

    def test_a_bare_token_is_accepted(self):
        self.assertEqual(AniListTracker._extract_token("abc123"), "abc123")

    def test_a_token_is_read_from_the_url_fragment(self):
        url = "https://anilist.co/api/v2/oauth/pin#access_token=abc&token_type=Bearer"
        self.assertEqual(AniListTracker._extract_token(url), "abc")

    def test_a_token_is_read_from_the_query_string(self):
        url = "https://example.invalid/cb?access_token=xyz"
        self.assertEqual(AniListTracker._extract_token(url), "xyz")

    def test_an_empty_redirect_yields_nothing(self):
        self.assertEqual(AniListTracker._extract_token(""), "")
        self.assertEqual(AniListTracker._extract_token("https://x.invalid/cb"), "")

    def test_search_maps_the_response(self):
        tracker = self._tracker(FakeResponse({"data": {"Page": {"media": [_ANILIST_MEDIA]}}}))
        results = tracker.search("berserk")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].remote_id, "30002")
        self.assertEqual(results[0].total_chapters, 374.0)
        self.assertEqual(results[0].start_date, "1989")

    def test_search_rescales_the_score_to_ten(self):
        """AniList reports out of 100; the app works in 0-10."""
        tracker = self._tracker(FakeResponse({"data": {"Page": {"media": [_ANILIST_MEDIA]}}}))
        self.assertAlmostEqual(tracker.search("berserk")[0].score, 9.2)

    def test_refresh_reads_the_list_entry(self):
        payload = {"data": {"Media": dict(_ANILIST_MEDIA, mediaListEntry={
            "id": 555, "status": "CURRENT", "progress": 42, "score": 8.0,
            "startedAt": {"year": 2020, "month": 1, "day": 2},
            "completedAt": {"year": None},
        })}}
        tracker = self._tracker(FakeResponse(payload))
        entry = tracker.refresh(TrackEntry(remote_id="30002"))
        self.assertEqual(entry.progress, 42.0)
        self.assertEqual(entry.status, STATUS_READING)
        self.assertEqual(entry.library_id, "555")
        self.assertIsNotNone(entry.started_at)
        self.assertIsNone(entry.finished_at)

    def test_status_maps_both_ways(self):
        payload = {"data": {"Media": dict(_ANILIST_MEDIA, mediaListEntry={
            "id": 1, "status": "COMPLETED", "progress": 374, "score": 10.0,
        })}}
        tracker = self._tracker(FakeResponse(payload))
        self.assertEqual(tracker.refresh(TrackEntry(remote_id="1")).status, STATUS_COMPLETED)

    def test_update_sends_the_score_out_of_one_hundred(self):
        tracker = self._tracker(FakeResponse({"data": {"SaveMediaListEntry": {
            "id": 5, "status": "CURRENT", "progress": 10, "score": 8.0,
        }}}))
        tracker.update(TrackEntry(remote_id="1", status=STATUS_READING, progress=10, score=8.0))
        sent = tracker._session.calls[0][2]["json"]["variables"]
        self.assertEqual(sent["score"], 80.0)
        self.assertEqual(sent["progress"], 10)

    def test_a_missing_token_raises_an_auth_error(self):
        tracker = self._tracker(FakeResponse(), token=None)
        with self.assertRaises(TrackerAuthError):
            tracker.search("x")

    def test_http_401_raises_an_auth_error(self):
        tracker = self._tracker(FakeResponse(status_code=401))
        with self.assertRaises(TrackerAuthError):
            tracker.search("x")

    def test_an_invalid_token_graphql_error_raises_an_auth_error(self):
        """AniList reports a bad token as a GraphQL error, not a 401."""
        tracker = self._tracker(FakeResponse({"errors": [{"message": "Invalid token"}]}))
        with self.assertRaises(TrackerAuthError):
            tracker.search("x")

    def test_a_generic_graphql_error_raises_a_tracker_error(self):
        tracker = self._tracker(FakeResponse({"errors": [{"message": "Too complex"}]}))
        with self.assertRaises(TrackerError) as caught:
            tracker.search("x")
        self.assertNotIsInstance(caught.exception, TrackerAuthError)

    def test_a_rate_limit_is_reported_clearly(self):
        tracker = self._tracker(FakeResponse(status_code=429))
        with self.assertRaises(TrackerError) as caught:
            tracker.search("x")
        self.assertIn("rate limit", str(caught.exception).lower())

    def test_an_unreadable_body_raises_a_tracker_error(self):
        tracker = self._tracker(FakeResponse(ValueError("not json")))
        with self.assertRaises(TrackerError):
            tracker.search("x")


# ── MyAnimeList ───────────────────────────────────────────────────────────

_MAL_NODE = {
    "id": 2,
    "title": "Berserk",
    "main_picture": {"large": "https://img.invalid/mal.jpg"},
    "num_chapters": 374,
    "status": "currently_publishing",
    "start_date": "1989-08-25",
    "mean": 9.47,
    "synopsis": "A dark fantasy.",
}


class MyAnimeListTests(unittest.TestCase):

    def _tracker(self, responses, token="tok", client_id="abc"):
        db = FakeDB({"tracker_mal_client_id": client_id})
        credentials = FakeCredentials(Token(token) if token else None)
        return MyAnimeListTracker(credentials, db=db, session=FakeSession(responses))

    def test_a_code_verifier_is_long_enough_for_pkce(self):
        verifier = generate_code_verifier()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)

    def test_verifiers_are_not_reused(self):
        self.assertNotEqual(generate_code_verifier(), generate_code_verifier())

    def test_authorization_url_uses_plain_pkce(self):
        """MAL only accepts the plain challenge method."""
        tracker = self._tracker(FakeResponse())
        url = tracker.authorization_url()
        self.assertIn("code_challenge_method=plain", url)
        self.assertIn("response_type=code", url)

    def test_the_verifier_is_stored_for_the_callback(self):
        tracker = self._tracker(FakeResponse())
        tracker.authorization_url()
        self.assertTrue(tracker._db.get_setting("tracker_mal_code_verifier"))

    def test_authorization_url_requires_a_client_id(self):
        tracker = self._tracker(FakeResponse(), client_id="")
        with self.assertRaises(TrackerError):
            tracker.authorization_url()

    def test_a_code_is_read_from_a_redirect_url(self):
        self.assertEqual(
            MyAnimeListTracker._extract_code("https://x.invalid/cb?code=abc&state=1"),
            "abc",
        )

    def test_a_bare_code_is_accepted(self):
        self.assertEqual(MyAnimeListTracker._extract_code("plaincode"), "plaincode")

    def test_login_stores_the_token_and_its_expiry(self):
        tracker = self._tracker(FakeResponse({
            "access_token": "at", "refresh_token": "rt", "expires_in": 2678400,
        }))
        tracker.authorization_url()
        self.assertTrue(tracker.complete_login("code123"))
        token = tracker._credentials.get_token("myanimelist")
        self.assertEqual(token.access_token, "at")
        self.assertGreater(token.expires_at, time.time())

    def test_login_clears_the_verifier_afterwards(self):
        tracker = self._tracker(FakeResponse({"access_token": "at", "expires_in": 10}))
        tracker.authorization_url()
        tracker.complete_login("code123")
        self.assertEqual(tracker._db.get_setting("tracker_mal_code_verifier"), "")

    def test_login_without_a_started_session_raises(self):
        tracker = self._tracker(FakeResponse())
        with self.assertRaises(TrackerError):
            tracker.complete_login("code123")

    def test_a_rejected_code_raises_an_auth_error(self):
        tracker = self._tracker(FakeResponse(status_code=400))
        tracker.authorization_url()
        with self.assertRaises(TrackerAuthError):
            tracker.complete_login("bad")

    def test_search_maps_the_response(self):
        tracker = self._tracker(FakeResponse({"data": [{"node": _MAL_NODE}]}))
        results = tracker.search("berserk")
        self.assertEqual(results[0].remote_id, "2")
        self.assertEqual(results[0].total_chapters, 374.0)
        self.assertEqual(results[0].start_date, "1989")
        self.assertAlmostEqual(results[0].score, 9.47)

    def test_refresh_reads_my_list_status(self):
        payload = dict(_MAL_NODE, my_list_status={
            "status": "reading", "num_chapters_read": 42, "score": 9,
            "start_date": "2020-01-02",
        })
        tracker = self._tracker(FakeResponse(payload))
        entry = tracker.refresh(TrackEntry(remote_id="2"))
        self.assertEqual(entry.progress, 42.0)
        self.assertEqual(entry.status, STATUS_READING)
        self.assertIsNotNone(entry.started_at)

    def test_an_unlisted_manga_has_no_library_id(self):
        tracker = self._tracker(FakeResponse(dict(_MAL_NODE)))
        self.assertEqual(tracker.refresh(TrackEntry(remote_id="2")).library_id, "")

    def test_plan_to_read_maps_back(self):
        payload = dict(_MAL_NODE, my_list_status={"status": "plan_to_read"})
        tracker = self._tracker(FakeResponse(payload))
        self.assertEqual(
            tracker.refresh(TrackEntry(remote_id="2")).status, STATUS_PLAN_TO_READ
        )

    def test_update_sends_integer_chapters(self):
        tracker = self._tracker(FakeResponse({
            "status": "reading", "num_chapters_read": 12, "score": 8,
        }))
        tracker.update(TrackEntry(remote_id="2", status=STATUS_READING, progress=12.7, score=8.0))
        sent = tracker._session.calls[0][2]["data"]
        self.assertEqual(sent["num_chapters_read"], 12)
        self.assertEqual(sent["status"], "reading")

    def test_an_expired_token_is_refreshed_before_the_call(self):
        refreshed = FakeResponse({"access_token": "new", "refresh_token": "rt2", "expires_in": 3600})
        data = FakeResponse(dict(_MAL_NODE))
        tracker = self._tracker([refreshed, data])
        tracker._credentials.set_token(
            "myanimelist", Token("old", "rt", expires_at=time.time() - 10)
        )
        tracker.refresh(TrackEntry(remote_id="2"))
        self.assertEqual(
            tracker._credentials.get_token("myanimelist").access_token, "new"
        )

    def test_a_refresh_with_no_refresh_token_raises_an_auth_error(self):
        tracker = self._tracker(FakeResponse())
        tracker._credentials.set_token("myanimelist", Token("old", "", expires_at=time.time() - 10))
        with self.assertRaises(TrackerAuthError):
            tracker.refresh(TrackEntry(remote_id="2"))

    def test_a_failed_refresh_clears_the_token(self):
        tracker = self._tracker(FakeResponse(status_code=400))
        tracker._credentials.set_token("myanimelist", Token("old", "rt", expires_at=time.time() - 10))
        with self.assertRaises(TrackerAuthError):
            tracker.refresh(TrackEntry(remote_id="2"))
        self.assertIsNone(tracker._credentials.get_token("myanimelist"))

    def test_an_empty_body_reads_back_as_an_empty_dict(self):
        tracker = self._tracker(FakeResponse(content=b""))
        self.assertEqual(tracker._request("DELETE", "/manga/2/my_list_status"), {})

    def test_a_rate_limit_is_reported_clearly(self):
        tracker = self._tracker(FakeResponse(status_code=429))
        with self.assertRaises(TrackerError) as caught:
            tracker.search("x")
        self.assertIn("rate limit", str(caught.exception).lower())


if __name__ == "__main__":
    unittest.main()
