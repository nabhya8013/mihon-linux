"""
Extension registry - discovers, loads, and manages source extensions.
Supports both native Python extensions and JVM-loaded Tachiyomi extensions.
"""
import json
from typing import Dict, List, Optional
from .base import Extension
from .allmanga import AllMangaExtension
from .mangadex import MangaDexExtension
from .mangafire import MangaFireExtension
from ..core.models import ExtensionInfo

import logging
logger = logging.getLogger("registry")

# A single upstream jar can register one source per UI language it supports -
# Tachiyomi/Mihon's real MangaDex extension alone provides 61. Kept to a
# setting (not hardcoded) so it stays adjustable without a code change; "all"
# always passes since it means language-agnostic, not "matches every filter".
DEFAULT_LANGUAGE_FILTER = ["en"]


class ExtensionRegistry:
    """Manages all available and installed extensions."""

    def __init__(self):
        self._extensions: Dict[str, Extension] = {}
        self._jvm_loaded = False
        self._load_builtins()

    def _language_allowed(self, language: str) -> bool:
        if not language or language == "all":
            return True
        try:
            from ..core.database import get_db
            allowed = json.loads(get_db().get_setting(
                "extension_language_filter", json.dumps(DEFAULT_LANGUAGE_FILTER)
            ))
        except Exception:
            allowed = DEFAULT_LANGUAGE_FILTER
        return language in allowed

    def _load_builtins(self):
        """
        Load built-in native Python extensions.

        MangaDex is the reference source that always works out of the box.
        Everything else beyond the listed built-ins is meant to come from
        user-installed Tachiyomi/Mihon APK extensions via the JVM bridge.
        """
        for ext_class in [MangaDexExtension, AllMangaExtension, MangaFireExtension]:
            try:
                ext = ext_class()
                self._extensions[ext.id] = ext
            except Exception as e:
                logger.error(f"Failed to load extension {ext_class.__name__}: {e}")

        # The local source reads a folder on disk rather than a website, so it
        # is registered separately and needs the database for its configured
        # library path.
        try:
            from ..core.database import get_db
            from .local import LocalSource
            local = LocalSource(db=get_db())
            self._extensions[local.id] = local
        except Exception as e:
            logger.error(f"Failed to load the local source: {e}")

    def load_jvm_extensions(self):
        """Load JVM-based Tachiyomi extensions via the bridge."""
        if self._jvm_loaded:
            return
        try:
            from .extension_manager import get_extension_manager
            manager = get_extension_manager()
            proxies = manager.load_all_installed()
            skipped = 0
            for proxy in proxies:
                if not self._language_allowed(proxy.info.language):
                    skipped += 1
                    continue
                self._extensions[proxy.id] = proxy
                logger.info(f"Registered JVM extension: {proxy.name} [{proxy.info.language}]")
            if skipped:
                logger.info(f"Skipped {skipped} JVM source(s) outside the language filter")
            self._jvm_loaded = True
        except Exception as e:
            logger.error(f"Failed to load JVM extensions: {e}")

    def register(self, extension: Extension):
        """Manually register an extension (e.g. after APK install)."""
        if not self._language_allowed(extension.info.language):
            logger.info(
                f"Skipping {extension.info.name} [{extension.info.language}]: "
                "outside the language filter"
            )
            return
        self._extensions[extension.id] = extension

    def unregister(self, extension_id: str):
        """Remove an extension from the registry."""
        self._extensions.pop(extension_id, None)

    def get(self, extension_id: str) -> Optional[Extension]:
        return self._extensions.get(extension_id)

    def get_all(self) -> List[Extension]:
        return list(self._extensions.values())

    def get_infos(self) -> List[ExtensionInfo]:
        return [ext.info for ext in self._extensions.values()]


# Singleton
_registry: Optional[ExtensionRegistry] = None

def get_registry() -> ExtensionRegistry:
    global _registry
    if _registry is None:
        _registry = ExtensionRegistry()
    return _registry
