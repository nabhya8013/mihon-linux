"""
Extension registry - discovers, loads, and manages source extensions.
"""
from typing import Dict, List, Optional
from .base import Extension
from .allmanga import AllMangaExtension
from .mangadex import MangaDexExtension
from ..core.models import ExtensionInfo


class ExtensionRegistry:
    """Manages all available and installed extensions."""

    def __init__(self):
        self._extensions: Dict[str, Extension] = {}
        self._load_builtins()

    def _load_builtins(self):
        """Load built-in extensions."""
        for ext_class in [MangaDexExtension, AllMangaExtension]:
            try:
                ext = ext_class()
                self._extensions[ext.id] = ext
            except Exception as e:
                print(f"Failed to load extension {ext_class.__name__}: {e}")

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
