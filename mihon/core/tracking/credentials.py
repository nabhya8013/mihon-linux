"""
Tracker credential storage.

OAuth tokens are bearer credentials for the user's AniList and MyAnimeList
accounts. Keeping them in the app's SQLite file — which is what the empty
``tracker_anilist_token`` setting implied — puts them in plain text next to
the library, readable by anything running as the user and captured by any
backup of the data directory.

This module stores them in the login keyring through libsecret instead, over
the SecretService D-Bus API. When no keyring is available (a headless session,
a container, a system without gnome-keyring or KWallet), it falls back to the
settings table and says so, rather than refusing to work.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("tracking.credentials")

SCHEMA_NAME = "io.github.nabhya8013.MihonLinux.Tracker"
SETTING_PREFIX = "tracker_token_"


@dataclass
class Token:
    """An OAuth token plus what is needed to know when it expires."""

    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0

    @property
    def is_expired(self) -> bool:
        # Treat a token expiring within the minute as already expired, so a
        # request does not start with a token that dies mid-flight.
        return bool(self.expires_at) and time.time() >= (self.expires_at - 60)

    def to_json(self) -> str:
        return json.dumps({
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        })

    @classmethod
    def from_json(cls, raw: str) -> Optional["Token"]:
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
        token = cls(
            access_token=str(data.get("access_token") or ""),
            refresh_token=str(data.get("refresh_token") or ""),
            expires_at=float(data.get("expires_at") or 0.0),
        )
        return token if token.access_token else None


def _load_secret_module():
    """The libsecret binding, or None when it is not installed."""
    try:
        import gi
        gi.require_version("Secret", "1")
        from gi.repository import Secret
        return Secret
    except (ImportError, ValueError) as exc:
        logger.info("libsecret unavailable, falling back to database storage: %s", exc)
        return None


class CredentialStore:
    """
    Tracker tokens, in the login keyring when one is available.

    ``db`` is only used for the fallback path and for recording which backend
    is in use, so the UI can warn the user their tokens are not encrypted.
    """

    def __init__(self, db, secret_module=None, force_fallback: bool = False):
        self._db = db
        self._lock = threading.Lock()
        self._cache: dict = {}

        self._secret = None if force_fallback else (
            secret_module if secret_module is not None else _load_secret_module()
        )
        self._schema = None
        if self._secret is not None:
            try:
                self._schema = self._secret.Schema.new(
                    SCHEMA_NAME,
                    self._secret.SchemaFlags.NONE,
                    {"provider": self._secret.SchemaAttributeType.STRING},
                )
            except Exception as exc:
                logger.warning("could not build the secret schema: %s", exc)
                self._secret = None

    # ── Backend ───────────────────────────────────────────────────────────

    @property
    def uses_keyring(self) -> bool:
        return self._secret is not None

    @property
    def backend_name(self) -> str:
        return "system keyring" if self.uses_keyring else "app database (not encrypted)"

    # ── Read and write ────────────────────────────────────────────────────

    def get_token(self, provider: str) -> Optional[Token]:
        with self._lock:
            if provider in self._cache:
                return self._cache[provider]

        raw = self._read_raw(provider)
        token = Token.from_json(raw)
        with self._lock:
            self._cache[provider] = token
        return token

    def set_token(self, provider: str, token: Optional[Token]):
        if token is None or not token.access_token:
            self.clear(provider)
            return

        self._write_raw(provider, token.to_json())
        with self._lock:
            self._cache[provider] = token

    def clear(self, provider: str):
        with self._lock:
            self._cache.pop(provider, None)

        if self._secret is not None:
            try:
                self._secret.password_clear_sync(
                    self._schema, {"provider": provider}, None
                )
            except Exception as exc:
                logger.warning("could not clear the keyring entry: %s", exc)

        try:
            self._db.set_setting(SETTING_PREFIX + provider, "")
        except Exception as exc:
            logger.warning("could not clear the stored token: %s", exc)

    # ── Internals ─────────────────────────────────────────────────────────

    def _read_raw(self, provider: str) -> str:
        if self._secret is not None:
            try:
                stored = self._secret.password_lookup_sync(
                    self._schema, {"provider": provider}, None
                )
                if stored:
                    return stored
            except Exception as exc:
                # A locked or absent keyring must not break the app; fall
                # through to whatever the database holds.
                logger.warning("keyring lookup failed for %s: %s", provider, exc)

        try:
            return self._db.get_setting(SETTING_PREFIX + provider, "")
        except Exception as exc:
            logger.warning("could not read the stored token: %s", exc)
            return ""

    def _write_raw(self, provider: str, raw: str):
        if self._secret is not None:
            try:
                self._secret.password_store_sync(
                    self._schema,
                    {"provider": provider},
                    self._secret.COLLECTION_DEFAULT,
                    f"Mihon tracker token ({provider})",
                    raw,
                    None,
                )
                # Stored in the keyring, so make sure no plaintext copy is
                # left behind from an earlier fallback write.
                self._db.set_setting(SETTING_PREFIX + provider, "")
                return
            except Exception as exc:
                logger.warning("keyring store failed for %s: %s", provider, exc)

        try:
            self._db.set_setting(SETTING_PREFIX + provider, raw)
        except Exception as exc:
            logger.error("could not store the token for %s: %s", provider, exc)


__all__ = ["CredentialStore", "SETTING_PREFIX", "Token"]
