"""
Incognito mode.

While it is on, reading leaves no trace: no history entry, no saved page,
no chapter marked read, and no tracker update. Android Mihon's incognito
mode pauses history the same way. The setting lives in the database like
every other preference, so it survives a restart until switched off.
"""
from __future__ import annotations

INCOGNITO_KEY = "incognito_mode"


def is_incognito(db) -> bool:
    return db.get_setting(INCOGNITO_KEY, "0") == "1"


def set_incognito(db, enabled: bool) -> None:
    db.set_setting(INCOGNITO_KEY, "1" if enabled else "0")


__all__ = ["INCOGNITO_KEY", "is_incognito", "set_incognito"]
