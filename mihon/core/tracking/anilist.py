"""
AniList tracker.

AniList exposes one GraphQL endpoint and supports the OAuth2 implicit grant,
which returns an access token directly in the redirect fragment. That matters
here because an implicit-grant client needs no client secret, and a desktop
app cannot keep one — anything shipped in the binary is public.

The user registers their own API client at
https://anilist.co/settings/developer and pastes the client id into Settings.
"""
from __future__ import annotations

import logging
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

logger = logging.getLogger("tracking.anilist")

API_URL = "https://graphql.anilist.co"
AUTH_URL = "https://anilist.co/api/v2/oauth/authorize"
# The out-of-band redirect AniList offers for clients with no callback server.
REDIRECT_URI = "https://anilist.co/api/v2/oauth/pin"

SETTING_CLIENT_ID = "tracker_anilist_client_id"

# AniList's own MediaListStatus enum, mapped onto the normalised statuses.
_TO_ANILIST = {
    STATUS_READING: "CURRENT",
    STATUS_COMPLETED: "COMPLETED",
    STATUS_ON_HOLD: "PAUSED",
    STATUS_DROPPED: "DROPPED",
    STATUS_PLAN_TO_READ: "PLANNING",
    STATUS_REREADING: "REPEATING",
}
_FROM_ANILIST = {v: k for k, v in _TO_ANILIST.items()}

SEARCH_QUERY = """
query ($query: String) {
  Page(perPage: 25) {
    media(search: $query, type: MANGA, format_not_in: [NOVEL]) {
      id
      title { romaji english }
      coverImage { large }
      chapters
      description(asHtml: false)
      status
      startDate { year month day }
      averageScore
      siteUrl
    }
  }
}
"""

ENTRY_QUERY = """
query ($mediaId: Int) {
  Media(id: $mediaId, type: MANGA) {
    id
    title { romaji english }
    chapters
    siteUrl
    mediaListEntry {
      id
      status
      progress
      score(format: POINT_10_DECIMAL)
      startedAt { year month day }
      completedAt { year month day }
    }
  }
}
"""

SAVE_MUTATION = """
mutation ($mediaId: Int, $status: MediaListStatus, $progress: Int, $score: Float) {
  SaveMediaListEntry(mediaId: $mediaId, status: $status, progress: $progress, scoreRaw: $score) {
    id
    status
    progress
    score(format: POINT_10_DECIMAL)
  }
}
"""

DELETE_MUTATION = """
mutation ($id: Int) {
  DeleteMediaListEntry(id: $id) { deleted }
}
"""


def _fuzzy_date_to_epoch(date: Optional[dict]) -> Optional[float]:
    """AniList's {year, month, day} object as an epoch, or None."""
    if not date or not date.get("year"):
        return None
    try:
        return time.mktime((
            int(date["year"]), int(date.get("month") or 1), int(date.get("day") or 1),
            0, 0, 0, 0, 0, -1,
        ))
    except (TypeError, ValueError, OverflowError):
        return None


class AniListTracker(TrackerService):

    id = "anilist"
    name = "AniList"
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
                "Set your AniList client ID in Settings first. Create one at "
                "https://anilist.co/settings/developer."
            )
        return (
            f"{AUTH_URL}?client_id={self.client_id}"
            f"&redirect_uri={REDIRECT_URI}&response_type=token"
        )

    def complete_login(self, redirect_response: str) -> bool:
        """
        Accept the pasted token, or a redirect URL containing one.

        The implicit grant puts the token in the URL fragment, which a browser
        never sends to a server, so AniList shows it on screen for the user to
        copy. Both forms are accepted.
        """
        token_value = self._extract_token(redirect_response)
        if not token_value:
            return False

        self._credentials.set_token(self.id, Token(access_token=token_value))
        try:
            # A cheap authenticated call confirms the token actually works,
            # rather than storing something that fails on first use.
            self._request("query { Viewer { id name } }", {})
        except TrackerError:
            self._credentials.clear(self.id)
            raise
        return True

    @staticmethod
    def _extract_token(value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        if "://" not in value:
            return value  # Already a bare token.

        parsed = urlparse(value)
        for part in (parsed.fragment, parsed.query):
            if not part:
                continue
            found = parse_qs(part).get("access_token")
            if found:
                return found[0]
        return ""

    # ── Data ──────────────────────────────────────────────────────────────

    def search(self, query: str) -> List[TrackSearchResult]:
        data = self._request(SEARCH_QUERY, {"query": query})
        media_list = (data.get("Page") or {}).get("media") or []

        results = []
        for media in media_list:
            titles = media.get("title") or {}
            start = media.get("startDate") or {}
            results.append(TrackSearchResult(
                remote_id=str(media.get("id") or ""),
                title=titles.get("english") or titles.get("romaji") or "",
                cover_url=(media.get("coverImage") or {}).get("large") or "",
                total_chapters=float(media.get("chapters") or 0),
                summary=media.get("description") or "",
                url=media.get("siteUrl") or "",
                publishing_status=(media.get("status") or "").replace("_", " ").title(),
                start_date=str(start.get("year") or ""),
                # AniList scores out of 100; the app works in the 0-10 scale.
                score=float(media.get("averageScore") or 0) / 10.0,
            ))
        return results

    def bind(self, remote_id: str) -> TrackEntry:
        entry = self._fetch_entry(remote_id)
        if entry.library_id:
            return entry
        # Not on the user's list yet, so create it as Reading.
        entry.status = STATUS_READING
        return self.update(entry)

    def refresh(self, entry: TrackEntry) -> TrackEntry:
        return self._fetch_entry(entry.remote_id)

    def update(self, entry: TrackEntry) -> TrackEntry:
        variables = {
            "mediaId": int(entry.remote_id),
            "status": _TO_ANILIST.get(entry.status, "CURRENT"),
            "progress": int(entry.progress),
            # scoreRaw is out of 100 even when reading back POINT_10_DECIMAL.
            "score": float(entry.score) * 10.0,
        }
        data = self._request(SAVE_MUTATION, variables)
        saved = data.get("SaveMediaListEntry") or {}

        updated = TrackEntry(**entry.__dict__)
        updated.library_id = str(saved.get("id") or entry.library_id)
        updated.status = _FROM_ANILIST.get(saved.get("status"), entry.status)
        updated.progress = float(saved.get("progress") or entry.progress)
        updated.score = float(saved.get("score") or entry.score)
        return updated

    def unbind(self, entry: TrackEntry):
        """Remove the entry from the user's AniList list."""
        if not entry.library_id:
            return
        self._request(DELETE_MUTATION, {"id": int(entry.library_id)})

    # ── Internals ─────────────────────────────────────────────────────────

    def _fetch_entry(self, remote_id) -> TrackEntry:
        data = self._request(ENTRY_QUERY, {"mediaId": int(remote_id)})
        media = data.get("Media") or {}
        titles = media.get("title") or {}
        listing = media.get("mediaListEntry") or {}

        return TrackEntry(
            provider=self.id,
            remote_id=str(media.get("id") or remote_id),
            library_id=str(listing.get("id") or ""),
            title=titles.get("english") or titles.get("romaji") or "",
            status=_FROM_ANILIST.get(listing.get("status"), STATUS_READING),
            progress=float(listing.get("progress") or 0),
            score=float(listing.get("score") or 0),
            total_chapters=float(media.get("chapters") or 0),
            url=media.get("siteUrl") or "",
            started_at=_fuzzy_date_to_epoch(listing.get("startedAt")),
            finished_at=_fuzzy_date_to_epoch(listing.get("completedAt")),
        )

    def _request(self, query: str, variables: dict) -> dict:
        token = self._credentials.get_token(self.id)
        if token is None:
            raise TrackerAuthError("Not logged in to AniList.")

        try:
            response = self._session.post(
                API_URL,
                json={"query": query, "variables": variables},
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=20,
            )
        except Exception as exc:
            raise TrackerError(f"AniList request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise TrackerAuthError("AniList rejected the stored token. Log in again.")
        if response.status_code == 429:
            raise TrackerError("AniList rate limit reached. Try again shortly.")
        if response.status_code >= 400:
            raise TrackerError(f"AniList returned HTTP {response.status_code}.")

        try:
            payload = response.json()
        except Exception as exc:
            raise TrackerError(f"AniList returned an unreadable response: {exc}") from exc

        errors = payload.get("errors")
        if errors:
            message = errors[0].get("message", "unknown error")
            # AniList reports an invalid token as a GraphQL error, not a 401.
            if "Invalid token" in message or "Unauthorized" in message:
                raise TrackerAuthError(f"AniList: {message}")
            raise TrackerError(f"AniList: {message}")

        return payload.get("data") or {}


__all__ = ["AniListTracker", "SETTING_CLIENT_ID"]
