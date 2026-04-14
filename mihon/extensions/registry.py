"""
Extension registry - discovers, loads, and manages source extensions.
Supports both native Python extensions and JVM-loaded Tachiyomi extensions.
"""
from typing import Dict, List, Optional
from .base import Extension
from .allmanga import AllMangaExtension
from .mangadex import MangaDexExtension
from ..core.models import ExtensionInfo

import logging
logger = logging.getLogger("registry")


class ExtensionRegistry:
    """Manages all available and installed extensions."""

    def __init__(self):
        self._extensions: Dict[str, Extension] = {}
        self._jvm_loaded = False
        self._load_builtins()

    def _load_builtins(self):
        """Load built-in native Python extensions."""
        for ext_class in [MangaDexExtension, AllMangaExtension]:
            try:
                ext = ext_class()
                self._extensions[ext.id] = ext
            except Exception as e:
                logger.error(f"Failed to load extension {ext_class.__name__}: {e}")

    def load_jvm_extensions(self):
        """Load JVM-based Tachiyomi extensions via the bridge."""
        if self._jvm_loaded:
            return
        try:
            from .extension_manager import get_extension_manager
            manager = get_extension_manager()
            proxies = manager.load_all_installed()
            for proxy in proxies:
                self._extensions[proxy.id] = proxy
                logger.info(f"Registered JVM extension: {proxy.name}")
            self._jvm_loaded = True
        except Exception as e:
            logger.error(f"Failed to load JVM extensions: {e}")

    def register(self, extension: Extension):
        """Manually register an extension (e.g. after APK install)."""
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
