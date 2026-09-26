"""
Shared HTTP session factory.

curl_cffi is preferred because it can impersonate browser TLS fingerprints,
which helps with sources protected by automated anti-bot checks. The fallback
keeps local development usable before dependencies are installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import Callable, Mapping, Optional

from .cookie_store import (
    COOKIE_JAR_PATH,
    apply_cookies_to_session,
    load_cookies_into_session,
    store_solution_cookies,
    store_solution_user_agent,
    user_agent_for_url,
)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_IMPERSONATE = "chrome124"
ANTI_BOT_STATUS_CODES = {403, 503}


@dataclass(frozen=True)
class ChallengeRequest:
    url: str
    status_code: int


@dataclass(frozen=True)
class ChallengeSolution:
    cookies: Mapping[str, str] = field(default_factory=dict)
    user_agent: Optional[str] = None


ChallengeSolver = Callable[[ChallengeRequest], Optional[ChallengeSolution]]

_solver_lock = threading.Lock()
_challenge_solver: Optional[ChallengeSolver] = None


def set_challenge_solver(solver: Optional[ChallengeSolver]) -> None:
    """Register the UI callback used when an anti-bot response is detected."""
    global _challenge_solver
    with _solver_lock:
        _challenge_solver = solver


def get_challenge_solver() -> Optional[ChallengeSolver]:
    with _solver_lock:
        return _challenge_solver


def _create_backend_session(headers: Mapping[str, str]):
    try:
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(impersonate=DEFAULT_IMPERSONATE)
        session.headers.update(headers)
        return session
    except Exception:
        import requests

        session = requests.Session()
        session.headers.update(headers)
        return session


class ChallengeAwareSession:
    """Small requests-compatible wrapper that retries after UI cookie solving."""

    def __init__(self, backend, cookie_jar_path: Path = COOKIE_JAR_PATH):
        self.backend = backend
        self.cookie_jar_path = cookie_jar_path
        load_cookies_into_session(self.backend, self.cookie_jar_path)

    @property
    def headers(self):
        return self.backend.headers

    @property
    def cookies(self):
        return self.backend.cookies

    def request(self, method: str, url: str, **kwargs):
        kwargs = self._request_kwargs_with_synced_user_agent(url, kwargs)
        response = self.backend.request(method, url, **kwargs)
        if not self._should_solve(response, kwargs):
            return response

        solver = get_challenge_solver()
        if solver is None:
            return response

        solution = solver(ChallengeRequest(url=url, status_code=response.status_code))
        if not solution:
            return response

        self._apply_solution(url, solution)
        self._close_response(response)
        retry_kwargs = self._retry_kwargs_with_solution(kwargs, solution)
        return self.backend.request(method, url, **retry_kwargs)

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def close(self):
        close = getattr(self.backend, "close", None)
        if close:
            close()

    def __getattr__(self, name: str):
        return getattr(self.backend, name)

    @staticmethod
    def _should_solve(response, kwargs: Mapping) -> bool:
        return getattr(response, "status_code", None) in ANTI_BOT_STATUS_CODES

    def _apply_solution(self, url: str, solution: ChallengeSolution) -> None:
        if solution.user_agent:
            self.headers["User-Agent"] = solution.user_agent
            store_solution_user_agent(url, solution.user_agent, self.cookie_jar_path)
        if solution.cookies:
            apply_cookies_to_session(self, url, solution.cookies)
            store_solution_cookies(url, solution.cookies, self.cookie_jar_path)

    def _request_kwargs_with_synced_user_agent(self, url: str, kwargs: Mapping) -> dict:
        synced_user_agent = user_agent_for_url(url, self.cookie_jar_path)
        if not synced_user_agent:
            return dict(kwargs)
        request_kwargs = dict(kwargs)
        headers = dict(request_kwargs.get("headers") or {})
        headers["User-Agent"] = synced_user_agent
        request_kwargs["headers"] = headers
        self.headers["User-Agent"] = synced_user_agent
        return request_kwargs

    @staticmethod
    def _close_response(response) -> None:
        close = getattr(response, "close", None)
        if close:
            close()

    @staticmethod
    def _retry_kwargs_with_solution(kwargs: Mapping, solution: ChallengeSolution) -> dict:
        retry_kwargs = dict(kwargs)
        if solution.user_agent:
            headers = dict(retry_kwargs.get("headers") or {})
            headers["User-Agent"] = solution.user_agent
            retry_kwargs["headers"] = headers
        return retry_kwargs


def create_http_session(
    headers: Optional[Mapping[str, str]] = None,
    cookie_jar_path: Path = COOKIE_JAR_PATH,
):
    """Create a requests-compatible HTTP session."""
    base_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        base_headers.update(headers)

    return ChallengeAwareSession(_create_backend_session(base_headers), cookie_jar_path)
