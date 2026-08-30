"""
Bridge-side challenge solver: a background thread that watches a shared
directory for `challenge_request.json` files written by the JVM bridge
`CloudflareInterceptor`, runs the registered Python challenge solver,
and writes a `challenge_response_<id>.json` file back.

The file-based handshake is necessary because the bridge JSON-RPC
channel only flows Python -> JVM, so the JVM cannot synchronously
call back into Python without deadlocking the calling thread.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from .cookie_store import COOKIE_JAR_PATH
from .database import DATA_DIR
from .http_client import (
    ANTI_BOT_STATUS_CODES,
    ChallengeRequest,
    ChallengeSolution,
    get_challenge_solver,
)

logger = logging.getLogger("challenge_bridge")

CHALLENGE_DIR_ENV = "MIHON_CHALLENGE_DIR"
CHALLENGE_DIR = DATA_DIR / "challenges"
REQUEST_FILE = "challenge_request.json"


def challenge_dir() -> Path:
    override = os.environ.get(CHALLENGE_DIR_ENV)
    if override:
        return Path(override)
    return CHALLENGE_DIR


def _read_request(path: Path) -> Optional[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("[challenge_bridge] cannot read request: %s", exc)
        return None
    if not isinstance(payload, dict):
        return None
    request_id = payload.get("request_id")
    url = payload.get("url")
    status_code = payload.get("status_code")
    if not request_id or not url or status_code not in ANTI_BOT_STATUS_CODES:
        return None
    return payload


def _write_response(path: Path, request_id: str, solved: bool) -> None:
    payload = {"request_id": request_id, "solved": solved}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def _solve_via_registered_solver(payload: dict) -> bool:
    solver = get_challenge_solver()
    if solver is None:
        logger.info(
            "[challenge_bridge] no solver registered; cannot solve %s",
            payload.get("url"),
        )
        return False
    request = ChallengeRequest(
        url=payload["url"],
        status_code=int(payload["status_code"]),
    )
    solution: Optional[ChallengeSolution] = None
    try:
        solution = solver(request)
    except Exception as exc:  # pragma: no cover - solver UI failure
        logger.exception("[challenge_bridge] solver raised: %s", exc)
        return False
    return solution is not None


class ChallengeSolverBridge:
    """Background watcher that bridges JVM CF challenges into Python."""

    def __init__(
        self,
        directory: Path = None,
        poll_interval: float = 0.25,
    ):
        self._dir = directory or challenge_dir()
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._seen_request_ids: set[str] = set()

    @property
    def directory(self) -> Path:
        return self._dir

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("[challenge_bridge] cannot create dir %s: %s", self._dir, exc)
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="challenge-bridge",
            daemon=True,
        )
        self._thread.start()
        logger.info("[challenge_bridge] watching %s", self._dir)
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:  # pragma: no cover
                logger.exception("[challenge_bridge] poll error: %s", exc)
            self._stop_event.wait(self._poll_interval)

    def _poll_once(self) -> None:
        request_path = self._dir / REQUEST_FILE
        if not request_path.exists():
            return
        payload = _read_request(request_path)
        if payload is None:
            return
        request_id = str(payload["request_id"])
        if request_id in self._seen_request_ids:
            return
        self._seen_request_ids.add(request_id)
        try:
            solved = _solve_via_registered_solver(payload)
        finally:
            # Always clear the request so the next challenge can be raised
            run_catching_unlink(request_path)
        response_path = self._dir / f"challenge_response_{request_id}.json"
        _write_response(response_path, request_id, solved)
        logger.info(
            "[challenge_bridge] solved=%s url=%s",
            solved,
            payload.get("url"),
        )


def run_catching_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


_instance: Optional[ChallengeSolverBridge] = None
_instance_lock = threading.Lock()


def get_challenge_bridge() -> ChallengeSolverBridge:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ChallengeSolverBridge()
        return _instance


def start_challenge_bridge() -> bool:
    bridge = get_challenge_bridge()
    bridge.start()
    os.environ.setdefault(CHALLENGE_DIR_ENV, str(bridge.directory))
    return True


__all__ = [
    "CHALLENGE_DIR",
    "CHALLENGE_DIR_ENV",
    "ChallengeSolverBridge",
    "REQUEST_FILE",
    "challenge_dir",
    "get_challenge_bridge",
    "start_challenge_bridge",
]
