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
        stem = Path(jar_path).stem
        self._installed[stem] = {
            "jar_path": jar_path,
            "source_class": result["source_class"],
            "name": result.get("name", "Unknown"),
            "version": result.get("version", "1.0"),
            "version_code": result.get("version_code", 0),
            "package": result.get("package", ""),
            "nsfw": result.get("nsfw", False),
            "native_lib_dir": result.get("native_lib_dir"),
            "apk_path": apk_path,
        }
        self._save_metadata()

        # Step 2: Load via bridge
        return self._load_extension(stem)

    def install_from_jar(
        self,
        jar_path: str,
        name: str,
        version: str = "1.0",
        version_code: int = 0,
        package: str = "",
        nsfw: bool = False,
        source_class: str = "",
    ) -> Optional[List[JvmProxyExtension]]:
        """
        Install a prebuilt extension JAR.

        Repos increasingly publish ready-made JARs alongside the APK. Using one
        skips androguard + dex2jar entirely, which removes the step most likely
        to fail on an unusual extension. With no AndroidManifest to read, the
        entry class is left empty and the bridge discovers it by scanning.
        """
        source = Path(jar_path)
        if not source.is_file():
            logger.error(f"JAR not found: {jar_path}")
            return None

        stem = source.stem
        target = EXTENSIONS_DIR / f"{stem}.jar"
        if source.resolve() != target.resolve():
            import shutil
            shutil.copy2(source, target)

        self._installed[stem] = {
            "jar_path": str(target),
            "source_class": source_class,
            "name": name,
            "version": version,
            "version_code": version_code,
            "package": package,
            "nsfw": nsfw,
            "native_lib_dir": None,
            "apk_path": "",
        }
        self._save_metadata()
        return self._load_extension(stem)

    def install_from_repo(
        self,
        entry,
        progress: Optional[callable] = None,
    ) -> Optional[List[JvmProxyExtension]]:
        """
        Download and install a RepoExtension, preferring its prebuilt JAR.

        Any previously installed build of the same package is removed first so
        an update replaces rather than duplicates the extension.
        """
        from .repo_manager import get_repo_manager

        downloaded = get_repo_manager().download_artifact(entry, progress=progress)
        if not downloaded:
            logger.error(f"Could not download {entry.display_name}")
            return None

        path, kind = downloaded
        try:
            for stem, meta in list(self._installed.items()):
                if entry.pkg and meta.get("package") == entry.pkg:
                    self.uninstall(stem)

            if kind == "jar":
                return self.install_from_jar(
                    path,
                    name=entry.display_name,
                    version=entry.version,
                    version_code=entry.version_code,
                    package=entry.pkg,
                    nsfw=entry.nsfw,
                )
            return self.install_from_apk(path)
        finally:
            # The download is a temp file; the installed copy lives in
            # EXTENSIONS_DIR, so the original is never needed again.
            if os.path.exists(path) and str(EXTENSIONS_DIR) not in path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

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

        if not self._ensure_bridge():
            return None

        bridge = get_bridge()
        params = {
            "jarPath": meta["jar_path"],
            # Empty for prebuilt JARs — the bridge scans the archive instead.
            "classNames": meta.get("source_class") or "",
            "nsfw": bool(meta.get("nsfw", False)),
        }
        if meta.get("native_lib_dir"):
            params["nativeLibDir"] = meta["native_lib_dir"]
        try:
            result = bridge.call("extension.load", params, timeout=60.0)
        except BridgeError as e:
            logger.error(f"Failed to load extension {stem}: {e}")
            logger.error("bridge error loading %s: %s", stem, e)
            return None

        if not result:
            logger.warning(f"Bridge returned empty result for {stem}")
            return None

        sources = result.get("sources", [])
        if not sources:
            loaded_count = result.get("loaded", 0)
            logger.warning(f"Extension {stem} loaded {loaded_count} sources but none were successful")
            logger.error(
                "extension %s: 0 sources loaded (class loading failed; "
                "check bridge stderr for details)", stem
            )
            return None

        proxies = []
        for src in sources:
            ext_id = src.get("id", 0)
            proxy = JvmProxyExtension(
                extension_id=ext_id,
                name=src.get("name", meta["name"]),
                lang=src.get("lang", "en"),
                base_url=src.get("baseUrl", ""),
                supports_latest=src.get("supportsLatest", False),
                version=meta.get("version", "1.0"),
                nsfw=bool(src.get("nsfw", meta.get("nsfw", False))),
                has_settings=bool(src.get("isConfigurable", False)),
                package=meta.get("package", ""),
                jar_stem=stem,
            )
            self._proxies[proxy.info.id] = proxy
            proxies.append(proxy)

        logger.info(f"Loaded {len(proxies)} source(s) from {stem}")
        logger.info(
            "loaded %d source(s) from %s: %s",
            len(proxies), stem, [p.name for p in proxies]
        )
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
        """Remove an installed extension: JAR, native libs, metadata, proxies."""
        meta = self._installed.pop(stem, None)
        if not meta:
            logger.warning(f"uninstall: no installed extension with stem {stem}")
            return False

        jar_path = meta.get("jar_path", "")
        if jar_path and os.path.exists(jar_path):
            try:
                os.remove(jar_path)
            except OSError as e:
                logger.error(f"Could not remove JAR {jar_path}: {e}")

        native_dir = meta.get("native_lib_dir")
        if native_dir:
            import shutil
            shutil.rmtree(Path(native_dir).parent, ignore_errors=True)

        for ext_id in [k for k, p in self._proxies.items() if p.jar_stem == stem]:
            self._proxies.pop(ext_id, None)

        self._save_metadata()
        logger.info(f"Uninstalled extension: {stem}")
        return True

    def find_stem_for_extension_id(self, extension_id: str) -> Optional[str]:
        """Map a registry extension id (e.g. 'jvm_123') back to its JAR stem."""
        proxy = self._proxies.get(extension_id)
        return proxy.jar_stem if proxy else None

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


def get_extension_manager() -> ExtensionManager:
    return ExtensionManager.get_instance()
