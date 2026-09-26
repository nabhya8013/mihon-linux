"""
MyAnimeList tracker.

MAL's v2 API uses OAuth2 with PKCE, so a desktop client needs a client id but
no client secret — the code verifier takes the secret's place. The user
registers their own client at https://myanimelist.net/apiconfig and pastes the
id into Settings.

MAL only accepts the ``plain`` code challenge method, which is why the
verifier is sent unhashed below.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from ..http_client import create_http_session
from .base import (
    STATUS_COMPLETED,
    STATUS_DROPPED,
    STATUS_ON_HOLD,
    STATUS_PLAN_TO_READ,
    STATUS_READING,
    STATUS_REREADING,
    TrackEntry,
    TrackerAuthError,
    TrackerError,
    TrackerService,
    TrackSearchResult,
)
from .credentials import Token

logger = logging.getLogger("tracking.mal")

API_URL = "https://api.myanimelist.net/v2"
AUTH_URL = "https://myanimelist.net/v1/oauth2/authorize"
TOKEN_URL = "https://myanimelist.net/v1/oauth2/token"

SETTING_CLIENT_ID = "tracker_mal_client_id"
SETTING_VERIFIER = "tracker_mal_code_verifier"

_TO_MAL = {
    STATUS_READING: "reading",
    STATUS_COMPLETED: "completed",
    STATUS_ON_HOLD: "on_hold",
    STATUS_DROPPED: "dropped",
    STATUS_PLAN_TO_READ: "plan_to_read",
    # MAL has no "rereading" status; it is a flag on a reading entry.
    STATUS_REREADING: "reading",
}
_FROM_MAL = {
    "reading": STATUS_READING,
    "completed": STATUS_COMPLETED,
    "on_hold": STATUS_ON_HOLD,
    "dropped": STATUS_DROPPED,
    "plan_to_read": STATUS_PLAN_TO_READ,
}

_LIST_FIELDS = "id,title,main_picture,num_chapters,status,start_date,mean,synopsis,my_list_status"


def generate_code_verifier() -> str:
    """A PKCE verifier: 43-128 characters of unreserved URL-safe text."""
    return base64.urlsafe_b64encode(os.urandom(64)).decode("ascii").rstrip("=")[:128]


def _parse_date(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return time.mktime(time.strptime(value, fmt))
        except ValueError:
            continue
    return None


class MyAnimeListTracker(TrackerService):

    id = "myanimelist"
    name = "MyAnimeList"
    max_score = 10.0

    def __init__(self, credentials, db=None, session=None):
        super().__init__(credentials)
        self._db = db
        self._session = session or create_http_session()

    # ── Configuration ─────────────────────────────────────────────────────

    @property
    def client_id(self) -> str:
        if self._db is None:
            return ""
        return (self._db.get_setting(SETTING_CLIENT_ID, "") or "").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id)

    # ── Authentication ────────────────────────────────────────────────────

    def authorization_url(self) -> str:
        if not self.is_configured:
            raise TrackerError(
                "Set your MyAnimeList client ID in Settings first. Create one at "
                "https://myanimelist.net/apiconfig."
            )
        verifier = generate_code_verifier()
        # The verifier has to survive until the user pastes the code back, so
        # it is stored rather than held in memory.
        self._db.set_setting(SETTING_VERIFIER, verifier)
        return (
            f"{AUTH_URL}?response_type=code&client_id={self.client_id}"
            f"&code_challenge={verifier}&code_challenge_method=plain"
        )

    def complete_login(self, redirect_response: str) -> bool:
        code = self._extract_code(redirect_response)
        if not code:
            return False

        verifier = self._db.get_setting(SETTING_VERIFIER, "") if self._db else ""
        if not verifier:
            raise TrackerError(
                "The login session expired. Start the MyAnimeList login again."
            )

        try:
            response = self._session.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "code": code,
                    "code_verifier": verifier,
                    "grant_type": "authorization_code",
                },
                timeout=20,
            )
        except Exception as exc:
            raise TrackerError(f"MyAnimeList token request failed: {exc}") from exc

        if response.status_code >= 400:
            raise TrackerAuthError(
                f"MyAnimeList rejected the login code (HTTP {response.status_code})."
            )

        payload = response.json()
        self._store_token(payload)
        if self._db:
            self._db.set_setting(SETTING_VERIFIER, "")
        return True

    @staticmethod
    def _extract_code(value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        if "://" not in value:
            return value
        found = parse_qs(urlparse(value).query).get("code")
        return found[0] if found else ""

    def _store_token(self, payload: dict):
        expires_in = float(payload.get("expires_in") or 0)
        self._credentials.set_token(self.id, Token(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=str(payload.get("refresh_token") or ""),
            expires_at=time.time() + expires_in if expires_in else 0.0,
        ))

    def _refresh_token(self) -> Token:
        """
        Exchange the refresh token for a new access token.

        MAL access tokens last about a month, so without this the user would
        have to log in again every few weeks.
        """
        token = self._credentials.get_token(self.id)
        if token is None or not token.refresh_token:
            raise TrackerAuthError("MyAnimeList session expired. Log in again.")

        try:
            response = self._session.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": token.refresh_token,
                },
                timeout=20,
            )
        except Exception as exc:
            raise TrackerError(f"MyAnimeList refresh failed: {exc}") from exc

        if response.status_code >= 400:
            self._credentials.clear(self.id)
            raise TrackerAuthError("MyAnimeList session expired. Log in again.")

        self._store_token(response.json())
        return self._credentials.get_token(self.id)

    # ── Data ──────────────────────────────────────────────────────────────

    def search(self, query: str) -> List[TrackSearchResult]:
        payload = self._request(
            "GET", "/manga",
            params={"q": query[:64], "limit": 25, "fields": _LIST_FIELDS},
        )
        results = []
        for item in payload.get("data") or []:
            node = item.get("node") or {}
            results.append(TrackSearchResult(
                remote_id=str(node.get("id") or ""),
                title=node.get("title") or "",
                cover_url=(node.get("main_picture") or {}).get("large") or "",
                total_chapters=float(node.get("num_chapters") or 0),
                summary=node.get("synopsis") or "",
                url=f"https://myanimelist.net/manga/{node.get('id')}",
                publishing_status=(node.get("status") or "").replace("_", " ").title(),
                start_date=(node.get("start_date") or "")[:4],
                score=float(node.get("mean") or 0),
            ))
        return results

    def bind(self, remote_id: str) -> TrackEntry:
        entry = self._fetch_entry(remote_id)
        if entry.library_id:
            return entry
        entry.status = STATUS_READING
        return self.update(entry)

    def refresh(self, entry: TrackEntry) -> TrackEntry:
        return self._fetch_entry(entry.remote_id)

    def update(self, entry: TrackEntry) -> TrackEntry:
        data = {
            "status": _TO_MAL.get(entry.status, "reading"),
            "num_chapters_read": int(entry.progress),
            "score": int(round(entry.score)),
        }
        if entry.status == STATUS_REREADING:
            data["is_rereading"] = "true"

        payload = self._request(
            "PUT", f"/manga/{entry.remote_id}/my_list_status", data=data
        )

        updated = TrackEntry(**entry.__dict__)
        updated.library_id = str(entry.remote_id)
        updated.status = _FROM_MAL.get(payload.get("status"), entry.status)
        updated.progress = float(payload.get("num_chapters_read") or entry.progress)
        updated.score = float(payload.get("score") or entry.score)
        if payload.get("is_rereading"):
            updated.status = STATUS_REREADING
        return updated

    def unbind(self, entry: TrackEntry):
        """Remove the entry from the user's MyAnimeList list."""
        if not entry.remote_id:
            return
        self._request("DELETE", f"/manga/{entry.remote_id}/my_list_status")

    # ── Internals ─────────────────────────────────────────────────────────

    def _fetch_entry(self, remote_id) -> TrackEntry:
        node = self._request("GET", f"/manga/{remote_id}", params={"fields": _LIST_FIELDS})
        listing = node.get("my_list_status") or {}

        status = _FROM_MAL.get(listing.get("status"), STATUS_READING)
        if listing.get("is_rereading"):
            status = STATUS_REREADING

        return TrackEntry(
            provider=self.id,
            remote_id=str(node.get("id") or remote_id),
            # MAL has no separate list-entry id: the manga id addresses it.
            library_id=str(node.get("id") or "") if listing else "",
            title=node.get("title") or "",
            status=status,
            progress=float(listing.get("num_chapters_read") or 0),
            score=float(listing.get("score") or 0),
            total_chapters=float(node.get("num_chapters") or 0),
            url=f"https://myanimelist.net/manga/{node.get('id')}",
            started_at=_parse_date(listing.get("start_date")),
            finished_at=_parse_date(listing.get("finish_date")),
        )

    def _request(self, method: str, path: str, *, params=None, data=None) -> dict:
        token = self._credentials.get_token(self.id)
        if token is None:
            raise TrackerAuthError("Not logged in to MyAnimeList.")
        if token.is_expired:
            token = self._refresh_token()

        try:
            response = self._session.request(
                method,
                API_URL + path,
                params=params,
                data=data,
                headers={"Authorization": f"Bearer {token.access_token}"},
                timeout=20,
            )
        except Exception as exc:
            raise TrackerError(f"MyAnimeList request failed: {exc}") from exc

        if response.status_code == 401:
            # The token may have been revoked rather than merely expired; one
            # refresh attempt distinguishes the two.
            token = self._refresh_token()
            try:
                response = self._session.request(
                    method,
                    API_URL + path,
                    params=params,
                    data=data,
                    headers={"Authorization": f"Bearer {token.access_token}"},
                    timeout=20,
                )
            except Exception as exc:
                raise TrackerError(f"MyAnimeList request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise TrackerAuthError("MyAnimeList rejected the stored token. Log in again.")
        if response.status_code == 429:
            raise TrackerError("MyAnimeList rate limit reached. Try again shortly.")
        if response.status_code >= 400:
            raise TrackerError(f"MyAnimeList returned HTTP {response.status_code}.")

        if not response.content:
            return {}
        try:
            return response.json()
        except Exception as exc:
            raise TrackerError(f"MyAnimeList returned an unreadable response: {exc}") from exc


__all__ = ["MyAnimeListTracker", "SETTING_CLIENT_ID", "generate_code_verifier"]
