"""
Extension Manager — handles installing, loading, and managing
Tachiyomi APK extensions via the JVM bridge.
"""
import os
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict

from .apk_extractor import extract_apk_and_convert
from .jvm_bridge import get_bridge, BridgeError
from .jvm_proxy import JvmProxyExtension

logger = logging.getLogger("extension_manager")

# Where installed extension JARs and metadata live
EXTENSIONS_DIR = Path(
    os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
) / "mihon-linux" / "extensions"

METADATA_FILE = EXTENSIONS_DIR / "installed.json"


class ExtensionManager:
    """Manages the lifecycle of JVM-based Tachiyomi extensions."""

    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ExtensionManager()
        return cls._instance

    def __init__(self):
        self._installed: Dict[str, dict] = {}  # jar_stem -> metadata
        self._proxies: Dict[str, JvmProxyExtension] = {}  # extension_id -> proxy
        self._stem_to_proxy_ids: Dict[str, List[str]] = {}  # jar_stem -> [extension_id]
        self._proxy_to_stem: Dict[str, str] = {}  # extension_id -> jar_stem
        self._bridge_started = False
        EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_metadata()

    # ── Metadata persistence ──────────────────────────────────────────────

    def _load_metadata(self):
        if METADATA_FILE.exists():
            try:
                self._installed = json.loads(METADATA_FILE.read_text())
            except Exception as e:
                logger.error(f"Failed to load extension metadata: {e}")
                self._installed = {}

    def _save_metadata(self):
        try:
            METADATA_FILE.write_text(json.dumps(self._installed, indent=2))
        except Exception as e:
            logger.error(f"Failed to save extension metadata: {e}")

    # ── Install ───────────────────────────────────────────────────────────

    def install_from_apk(self, apk_path: str) -> Optional[List[JvmProxyExtension]]:
        """
        Install a Tachiyomi extension from an APK file.

        1. Extracts metadata from AndroidManifest
        2. Converts DEX → JAR via dex2jar
        3. Sends extension.load to the bridge
        4. Creates JvmProxyExtension instances
        """
        logger.info(f"Installing extension from: {apk_path}")

        # Step 1: Extract and convert
        result = extract_apk_and_convert(apk_path, str(EXTENSIONS_DIR))
        if not result:
            logger.error("APK extraction failed")
            return None

        jar_path = result["jar_path"]
        source_class = result["source_class"]
        ext_name = result.get("name", "Unknown")
        ext_version = result.get("version", "1.0")

        stem = Path(jar_path).stem
        self._installed[stem] = {
            "jar_path": jar_path,
            "source_class": source_class,
            "name": ext_name,
            "version": ext_version,
            "apk_path": apk_path,
        }
        self._save_metadata()

        # Force reload for this stem in case it was previously cached.
        self._clear_loaded_stem(stem)

        # Step 2: Load via bridge
        return self._load_extension(stem)

    # ── Load ──────────────────────────────────────────────────────────────

    def _ensure_bridge(self) -> bool:
        if not self._bridge_started:
            bridge = get_bridge()
            if bridge.start():
                self._bridge_started = True
            else:
                logger.error("Failed to start JVM bridge")
                return False
        return True

    def _load_extension(self, stem: str) -> Optional[List[JvmProxyExtension]]:
        """Load a single installed extension into the bridge."""
        meta = self._installed.get(stem)
        if not meta:
            return None

        cached = self._get_cached_stem_proxies(stem)
        if cached is not None:
            return cached

        if not self._ensure_bridge():
            return None

        bridge = get_bridge()
        try:
            result = bridge.call("extension.load", {
                "jarPath": meta["jar_path"],
                "classNames": meta["source_class"],
            }, timeout=30.0)
        except BridgeError as e:
            logger.error(f"Failed to load extension {stem}: {e}")
            print(f"[ext_manager] Bridge error loading {stem}: {e}")
            return None

        if not result:
            logger.warning(f"Bridge returned empty result for {stem}")
            return None

        sources = result.get("sources", [])
        if not sources:
            loaded_count = result.get("loaded", 0)
            logger.warning(f"Extension {stem} loaded {loaded_count} sources but none were successful")
            print(f"[ext_manager] Extension {stem}: 0 sources loaded (class loading failed — check bridge stderr for details)")
            return None

        proxies = []
        self._clear_loaded_stem(stem)
        for src in sources:
            ext_id = src.get("id", 0)
            proxy = JvmProxyExtension(
                extension_id=ext_id,
                name=src.get("name", meta["name"]),
                lang=src.get("lang", "en"),
                base_url=src.get("baseUrl", ""),
                supports_latest=src.get("supportsLatest", False),
            )
            self._proxies[proxy.info.id] = proxy
            self._proxy_to_stem[proxy.info.id] = stem
            proxies.append(proxy)
        self._stem_to_proxy_ids[stem] = [proxy.info.id for proxy in proxies]

        logger.info(f"Loaded {len(proxies)} source(s) from {stem}")
        print(f"[ext_manager] Loaded {len(proxies)} source(s) from {stem}: {[p.name for p in proxies]}")
        return proxies

    def load_all_installed(self) -> List[JvmProxyExtension]:
        """Load all previously installed extensions."""
        all_proxies = []
        for stem in list(self._installed.keys()):
            meta = self._installed[stem]
            if not os.path.exists(meta.get("jar_path", "")):
                logger.warning(f"JAR missing for {stem}, skipping")
                continue
            proxies = self._load_extension(stem)
            if proxies:
                all_proxies.extend(proxies)
        return all_proxies

    # ── Uninstall ─────────────────────────────────────────────────────────

    def uninstall(self, stem: str) -> bool:
        removed = self._remove_stem(stem, persist=True)
        if removed:
            logger.info(f"Uninstalled extension: {stem}")
        return removed

    def uninstall_by_extension_id(self, extension_id: str) -> bool:
        stem = self._proxy_to_stem.get(extension_id)
        if not stem:
            return False
        return self.uninstall(stem)

    def _remove_stem(self, stem: str, persist: bool) -> bool:
        meta = self._installed.pop(stem, None)
        if not meta:
            return False

        self._clear_loaded_stem(stem)

        jar_path = meta.get("jar_path", "")
        if jar_path and os.path.exists(jar_path):
            try:
                os.remove(jar_path)
            except OSError as e:
                logger.warning(f"Could not remove JAR for {stem}: {e}")

        if persist:
            self._save_metadata()
        return True

    # ── Accessors ─────────────────────────────────────────────────────────

    def get_all_proxies(self) -> List[JvmProxyExtension]:
        return list(self._proxies.values())

    def get_proxy(self, extension_id: str) -> Optional[JvmProxyExtension]:
        return self._proxies.get(extension_id)

    def get_installed_metadata(self) -> Dict[str, dict]:
        return dict(self._installed)

    def stop(self):
        """Stop the bridge when the app exits."""
        if self._bridge_started:
            get_bridge().stop()
            self._bridge_started = False

    def _get_cached_stem_proxies(self, stem: str) -> Optional[List[JvmProxyExtension]]:
        proxy_ids = self._stem_to_proxy_ids.get(stem)
        if not proxy_ids:
            return None
        proxies = []
        for extension_id in proxy_ids:
            proxy = self._proxies.get(extension_id)
            if proxy is None:
                return None
            proxies.append(proxy)
        return proxies

    def _clear_loaded_stem(self, stem: str):
        proxy_ids = self._stem_to_proxy_ids.pop(stem, [])
        for extension_id in proxy_ids:
            self._proxy_to_stem.pop(extension_id, None)
            self._proxies.pop(extension_id, None)


def get_extension_manager() -> ExtensionManager:
    return ExtensionManager.get_instance()
