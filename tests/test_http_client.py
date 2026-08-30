import builtins
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from mihon.core.http_client import (
    ChallengeAwareSession,
    DEFAULT_IMPERSONATE,
    DEFAULT_USER_AGENT,
    ChallengeSolution,
    create_http_session,
    set_challenge_solver,
)


class HttpClientTests(unittest.TestCase):
    def test_prefers_curl_cffi_with_browser_impersonation(self):
        class FakeSession:
            def __init__(self, impersonate=None):
                self.impersonate = impersonate
                self.headers = {}
                self.cookies = {}

        class FakeRequests:
            def __init__(self):
                self.session = None

            def Session(self, impersonate=None):
                self.session = FakeSession(impersonate=impersonate)
                return self.session

        fake_requests = FakeRequests()
        fake_curl_cffi = types.ModuleType("curl_cffi")
        fake_curl_cffi.requests = fake_requests

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(sys.modules, {"curl_cffi": fake_curl_cffi}):
                session = create_http_session(
                    {"Accept": "application/json"},
                    cookie_jar_path=Path(tmp) / "cookies.json",
                )

        self.assertIs(session.backend, fake_requests.session)
        self.assertEqual(session.backend.impersonate, DEFAULT_IMPERSONATE)
        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertEqual(session.headers["Accept"], "application/json")

    def test_falls_back_to_requests_when_curl_cffi_is_unavailable(self):
        real_import = builtins.__import__

        def import_without_curl_cffi(name, *args, **kwargs):
            if name == "curl_cffi":
                raise ImportError("curl_cffi unavailable")
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("builtins.__import__", side_effect=import_without_curl_cffi):
                session = create_http_session(
                    {"X-Test": "1"},
                    cookie_jar_path=Path(tmp) / "cookies.json",
                )

        self.assertEqual(session.headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertEqual(session.headers["X-Test"], "1")

    def test_anti_bot_response_invokes_solver_and_retries_once(self):
        class FakeCookies(dict):
            def set(self, name, value, domain="", path="/", secure=False):
                self[name] = value

        class FakeResponse:
            def __init__(self, status_code):
                self.status_code = status_code
                self.closed = False

            def close(self):
                self.closed = True

        class FakeBackend:
            def __init__(self):
                self.headers = {"User-Agent": "before"}
                self.cookies = FakeCookies()
                self.calls = []
                self.first = FakeResponse(403)
                self.second = FakeResponse(200)

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                return self.first if len(self.calls) == 1 else self.second

        backend = FakeBackend()
        requests_seen = []

        def solver(request):
            requests_seen.append(request)
            return ChallengeSolution(cookies={"cf_clearance": "ok"}, user_agent="SolvedUA")

        try:
            set_challenge_solver(solver)
            with tempfile.TemporaryDirectory() as tmp:
                session = ChallengeAwareSession(backend, Path(tmp) / "cookies.json")
                response = session.get("https://example.test/protected")
        finally:
            set_challenge_solver(None)

        self.assertIs(response, backend.second)
        self.assertTrue(backend.first.closed)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(requests_seen[0].status_code, 403)
        self.assertEqual(backend.cookies["cf_clearance"], "ok")
        self.assertEqual(backend.headers["User-Agent"], "SolvedUA")
        self.assertEqual(backend.calls[1][2]["headers"]["User-Agent"], "SolvedUA")

    def test_anti_bot_response_without_solver_is_not_retried(self):
        class FakeResponse:
            status_code = 503

        class FakeBackend:
            def __init__(self):
                self.headers = {}
                self.cookies = {}
                self.calls = 0

            def request(self, method, url, **kwargs):
                self.calls += 1
                return FakeResponse()

        try:
            set_challenge_solver(None)
            backend = FakeBackend()
            with tempfile.TemporaryDirectory() as tmp:
                response = ChallengeAwareSession(backend, Path(tmp) / "cookies.json").get(
                    "https://example.test/"
                )
        finally:
            set_challenge_solver(None)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(backend.calls, 1)

    def test_solver_cookies_are_persisted_and_loaded_into_new_session(self):
        class FakeCookies(dict):
            def __init__(self):
                super().__init__()
                self.set_calls = []

            def set(self, name, value, domain="", path="/", secure=False):
                self.set_calls.append((name, value, domain, path, secure))
                self[name] = value

        class FakeResponse:
            def __init__(self, status_code):
                self.status_code = status_code

            def close(self):
                pass

        class FakeBackend:
            def __init__(self):
                self.headers = {}
                self.cookies = FakeCookies()
                self.calls = 0

            def request(self, method, url, **kwargs):
                self.calls += 1
                return FakeResponse(403 if self.calls == 1 else 200)

        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "cookies.json"

            def solver(_request):
                return ChallengeSolution(
                    cookies={"cf_clearance": "ok"},
                    user_agent="SolvedUA",
                )

            try:
                set_challenge_solver(solver)
                first_backend = FakeBackend()
                ChallengeAwareSession(first_backend, cookie_path).get(
                    "https://example.test/protected"
                )
            finally:
                set_challenge_solver(None)

            payload = json.loads(cookie_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["cookies"][0]["domain"], "example.test")
            self.assertEqual(payload["cookies"][0]["name"], "cf_clearance")
            self.assertEqual(payload["cookies"][0]["value"], "ok")
            self.assertEqual(payload["user_agents"][0]["domain"], "example.test")
            self.assertEqual(payload["user_agents"][0]["user_agent"], "SolvedUA")

            second_backend = FakeBackend()
            ChallengeAwareSession(second_backend, cookie_path)
            self.assertEqual(
                second_backend.cookies.set_calls[0],
                ("cf_clearance", "ok", "example.test", "/", True),
            )

    def test_persisted_user_agent_is_applied_to_matching_domain_requests(self):
        class FakeCookies(dict):
            def set(self, name, value, domain="", path="/", secure=False):
                self[name] = value

        class FakeBackend:
            def __init__(self):
                self.headers = {"User-Agent": "DefaultUA"}
                self.cookies = FakeCookies()
                self.calls = []

            def request(self, method, url, **kwargs):
                self.calls.append((method, url, kwargs))
                response = type("FakeResponse", (), {})()
                response.status_code = 200
                return response

        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "cookies.json"
            cookie_path.write_text(json.dumps({
                "version": 1,
                "cookies": [],
                "user_agents": [{
                    "domain": "example.test",
                    "user_agent": "SolvedUA",
                    "updated_at": 1,
                }],
            }), encoding="utf-8")

            backend = FakeBackend()
            session = ChallengeAwareSession(backend, cookie_path)
            session.get("https://sub.example.test/path", headers={"Accept": "text/html"})

        self.assertEqual(backend.headers["User-Agent"], "SolvedUA")
        self.assertEqual(backend.calls[0][2]["headers"]["User-Agent"], "SolvedUA")
        self.assertEqual(backend.calls[0][2]["headers"]["Accept"], "text/html")


if __name__ == "__main__":
    unittest.main()
