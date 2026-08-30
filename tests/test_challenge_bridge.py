"""Tests for the JVM <-> Python Cloudflare challenge bridge."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mihon.core.challenge_bridge import (
    CHALLENGE_DIR_ENV,
    REQUEST_FILE,
    ChallengeSolverBridge,
    _read_request,
    _write_response,
    challenge_dir,
)
from mihon.core.http_client import (
    ChallengeRequest,
    ChallengeSolution,
    set_challenge_solver,
)


class ChallengeBridgeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._dir = Path(self._tmp.name)
        # Ensure no solver is leaking from another test
        set_challenge_solver(None)

    def _make_request_file(self, url: str, status_code: int = 403) -> str:
        request_id = f"cf-{int(time.time() * 1000)}-1"
        payload = {
            "request_id": request_id,
            "url": url,
            "status_code": status_code,
            "timeout_ms": 5000,
        }
        (self._dir / REQUEST_FILE).write_text(json.dumps(payload), encoding="utf-8")
        return request_id

    def test_read_request_parses_valid_payload(self):
        request_id = self._make_request_file("https://example.test/x")
        payload = _read_request(self._dir / REQUEST_FILE)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["request_id"], request_id)
        self.assertEqual(payload["url"], "https://example.test/x")
        self.assertEqual(payload["status_code"], 403)

    def test_read_request_rejects_non_anti_bot_status(self):
        self._make_request_file("https://example.test/x", status_code=200)
        self.assertIsNone(_read_request(self._dir / REQUEST_FILE))

    def test_read_request_rejects_missing_url(self):
        (self._dir / REQUEST_FILE).write_text(
            json.dumps({"request_id": "r", "status_code": 403}),
            encoding="utf-8",
        )
        self.assertIsNone(_read_request(self._dir / REQUEST_FILE))

    def test_write_response_round_trips(self):
        path = self._dir / "challenge_response_abc.json"
        _write_response(path, "abc", True)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload, {"request_id": "abc", "solved": True})

    def test_bridge_invokes_registered_solver_and_writes_response(self):
        def solver(request: ChallengeRequest):
            return ChallengeSolution(
                cookies={"cf_clearance": "ok"},
                user_agent="SolvedUA",
            )

        set_challenge_solver(solver)
        bridge = ChallengeSolverBridge(directory=self._dir, poll_interval=0.01)
        self.assertTrue(bridge.start())
        try:
            request_id = self._make_request_file("https://example.test/protected")
            response_path = self._dir / f"challenge_response_{request_id}.json"
            self.assertTrue(
                _wait_for(response_path, timeout=3.0),
                "Solver bridge did not write response in time",
            )
            payload = json.loads(response_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["request_id"], request_id)
            self.assertTrue(payload["solved"])
        finally:
            bridge.stop()
            set_challenge_solver(None)

    def test_bridge_reports_unsolved_when_no_solver_registered(self):
        bridge = ChallengeSolverBridge(directory=self._dir, poll_interval=0.01)
        self.assertTrue(bridge.start())
        try:
            request_id = self._make_request_file("https://example.test/x")
            response_path = self._dir / f"challenge_response_{request_id}.json"
            self.assertTrue(_wait_for(response_path, timeout=3.0))
            payload = json.loads(response_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["request_id"], request_id)
            self.assertFalse(payload["solved"])
        finally:
            bridge.stop()

    def test_bridge_recovers_from_solver_exception(self):
        def broken_solver(_request):
            raise RuntimeError("boom")

        set_challenge_solver(broken_solver)
        bridge = ChallengeSolverBridge(directory=self._dir, poll_interval=0.01)
        self.assertTrue(bridge.start())
        try:
            request_id = self._make_request_file("https://example.test/x")
            response_path = self._dir / f"challenge_response_{request_id}.json"
            self.assertTrue(_wait_for(response_path, timeout=3.0))
            payload = json.loads(response_path.read_text(encoding="utf-8"))
            self.assertFalse(payload["solved"])
        finally:
            bridge.stop()
            set_challenge_solver(None)

    def test_bridge_does_not_reprocess_same_request_id(self):
        seen = []

        def solver(_request):
            seen.append(True)
            return ChallengeSolution(cookies={"a": "b"})

        set_challenge_solver(solver)
        bridge = ChallengeSolverBridge(directory=self._dir, poll_interval=0.01)
        self.assertTrue(bridge.start())
        try:
            # Place a stable request_id and poll once
            (self._dir / REQUEST_FILE).write_text(
                json.dumps({
                    "request_id": "stable",
                    "url": "https://example.test/a",
                    "status_code": 403,
                    "timeout_ms": 5000,
                }),
                encoding="utf-8",
            )
            bridge._poll_once()
            bridge._poll_once()
            # The request file should already be deleted by the first poll
            self.assertFalse((self._dir / REQUEST_FILE).exists())
            self.assertEqual(len(seen), 1)
        finally:
            bridge.stop()
            set_challenge_solver(None)

    def test_challenge_dir_uses_env_override(self):
        with patch.dict(os.environ, {CHALLENGE_DIR_ENV: str(self._dir)}):
            self.assertEqual(challenge_dir(), self._dir)


def _wait_for(path: Path, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return False


if __name__ == "__main__":
    unittest.main()
