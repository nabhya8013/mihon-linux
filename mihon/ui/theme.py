"""
Appearance theme: System / Light / Dark, applied via Adw.StyleManager.

The app used to hardcode PREFER_DARK at activation with no way to change it.
Shared between app.py (applied once at startup) and the More -> Appearance
setting (applied live on change, no restart needed).
"""
from __future__ import annotations

import gi
gi.require_version("Adw", "1")
from gi.repository import Adw

from ..core.database import get_db

THEME_VALUES = ["system", "light", "dark"]

_SCHEME_BY_THEME = {
    "system": Adw.ColorScheme.DEFAULT,
    "light": Adw.ColorScheme.FORCE_LIGHT,
    "dark": Adw.ColorScheme.FORCE_DARK,
}


def apply_appearance_theme() -> None:
    """Set Adw.StyleManager's color scheme from the appearance_theme setting."""
    theme = get_db().get_setting("appearance_theme", "dark")
    scheme = _SCHEME_BY_THEME.get(theme, Adw.ColorScheme.FORCE_DARK)
    Adw.StyleManager.get_default().set_color_scheme(scheme)


__all__ = ["THEME_VALUES", "apply_appearance_theme"]
