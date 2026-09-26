"""
Extension repository client.

Mihon's extension ecosystem is decentralised: a repo is just a static directory
containing `index.min.json` plus an `apk/` and `icon/` folder. This module
fetches those indexes, tells the UI what is available/installed/outdated, and
downloads an APK so `ExtensionManager.install_from_apk` can take over.

Two index formats are in the wild and both are supported:

* **Modern** (Keiyoushi today) — an object with
  ``extensionList.extensions[]``; each entry carries absolute
  ``resources.apkUrl`` / ``resources.jarUrl`` / ``resources.iconUrl``.
  The prebuilt ``jarUrl`` lets us skip dex2jar conversion entirely.
* **Legacy** — a bare JSON array of ``{pkg, apk, code, version, nsfw}`` with
  files resolved relative to the repo root (``<base>/apk/<apk>``).

Note that Keiyoushi's ``index.min.json`` is now a two-entry "update your app"
stub; the real catalogue lives in ``index.json``, which is why that is tried
first.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from ..core.http_client import create_http_session

logger = logging.getLogger("repo_manager")

DEFAULT_REPO = "https://raw.githubusercontent.com/keiyoushi/extensions/repo"

DATA_DIR = Path(
    os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
) / "mihon-linux"
REPO_DIR = DATA_DIR / "repos"
ICON_DIR = REPO_DIR / "icons"
REPO_CONFIG = REPO_DIR / "repos.json"


@dataclass
class RepoExtension:
    """One extension entry from a repo index."""

    name: str
    pkg: str
    lang: str
    version: str
    version_code: int
    nsfw: bool
    repo_base: str
    apk_url: str = ""
    jar_url: str = ""
    icon_url: str = ""
    sources: List[dict] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """Strip the 'Tachiyomi: ' / 'Mihon: ' prefix repos put on every entry."""
        return re.sub(r"^(Tachiyomi|Mihon):\s*", "", self.name).strip()

    @property
    def icon_path(self) -> Path:
        return ICON_DIR / f"{self.pkg}.png"

    @property
    def languages(self) -> List[str]:
        """Distinct languages across the sources this extension provides."""
        langs = {str(src.get("language") or src.get("lang") or "").strip()
                 for src in self.sources}
        langs.discard("")
        return sorted(langs) or [self.lang]

    @property
    def prefers_jar(self) -> bool:
        """A prebuilt JAR skips dex2jar, so use it whenever the repo offers one."""
        return bool(self.jar_url)


def _normalise_base(url: str) -> str:
    """Accept either a repo root or a direct index URL and return the root."""
    url = url.strip().rstrip("/")
    for suffix in ("/index.min.json", "/index.json"):
        if url.endswith(suffix):
            return url[: -len(suffix)]
    return url


class RepoManager:
    """Fetches and caches extension repo indexes."""

    _instance: Optional["RepoManager"] = None

    @classmethod
    def get_instance(cls) -> "RepoManager":
        if cls._instance is None:
            cls._instance = RepoManager()
        return cls._instance

    def __init__(self):
        REPO_DIR.mkdir(parents=True, exist_ok=True)
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        self._repos: List[str] = []
        self._cache: Dict[str, List[RepoExtension]] = {}
        self._load_config()

    # ── Repo list ─────────────────────────────────────────────────────────

    def _load_config(self):
        if REPO_CONFIG.exists():
            try:
                data = json.loads(REPO_CONFIG.read_text())
                self._repos = [_normalise_base(u) for u in data.get("repos", []) if u.strip()]
            except Exception as e:
                logger.error(f"Could not read repo config: {e}")
        if not self._repos:
            self._repos = [DEFAULT_REPO]
            self._save_config()

    def _save_config(self):
        try:
            REPO_CONFIG.write_text(json.dumps({"repos": self._repos}, indent=2))
        except OSError as e:
            logger.error(f"Could not save repo config: {e}")

    def get_repos(self) -> List[str]:
        return list(self._repos)

    def add_repo(self, url: str) -> bool:
        base = _normalise_base(url)
        if not base.startswith(("http://", "https://")):
            logger.error(f"Rejected repo URL (not http/https): {url}")
            return False
        if base in self._repos:
            return False
        self._repos.append(base)
        self._save_config()
        return True

    def remove_repo(self, url: str) -> bool:
        base = _normalise_base(url)
        if base not in self._repos:
            return False
        self._repos.remove(base)
        self._cache.pop(base, None)
        self._save_config()
        return True

    # ── Index fetching ────────────────────────────────────────────────────

    def fetch_index(self, repo_base: str, force: bool = False) -> List[RepoExtension]:
        """Download and parse one repo's index. Cached in memory per session."""
        repo_base = _normalise_base(repo_base)
        if not force and repo_base in self._cache:
            return self._cache[repo_base]

        session = create_http_session()
        last_error: Optional[Exception] = None
        # index.json first: Keiyoushi's index.min.json is now an "update your
        # app" stub containing two placeholder entries.
        for name in ("index.json", "index.min.json"):
            url = f"{repo_base}/{name}"
            try:
                response = session.get(url, timeout=30)
                if response.status_code != 200:
                    last_error = RuntimeError(f"HTTP {response.status_code} for {url}")
                    continue
                entries = self._parse_index(response.json(), repo_base)
                self._cache[repo_base] = entries
                logger.info(f"{repo_base}: {len(entries)} extensions in index")
                return entries
            except Exception as e:
                last_error = e
                continue

        logger.error(f"Could not fetch index for {repo_base}: {last_error}")
        return []

    def _parse_index(self, payload, repo_base: str) -> List[RepoExtension]:
        """Parse either the modern object index or the legacy array index."""
        if isinstance(payload, dict):
            entries = self._parse_modern(payload, repo_base)
        elif isinstance(payload, list):
            entries = self._parse_legacy(payload, repo_base)
        else:
            logger.error(f"{repo_base}: unrecognised index format")
            return []
        entries.sort(key=lambda e: e.display_name.lower())
        return entries

    def _parse_modern(self, payload: dict, repo_base: str) -> List[RepoExtension]:
        raw_entries = (payload.get("extensionList") or {}).get("extensions")
        if not isinstance(raw_entries, list):
            logger.error(f"{repo_base}: object index has no extensionList.extensions")
            return []

        entries: List[RepoExtension] = []
        for raw in raw_entries:
            if not isinstance(raw, dict):
                continue
            pkg = raw.get("packageName") or ""
            if not pkg:
                continue
            resources = raw.get("resources") or {}
            sources = raw.get("sources") or []
            try:
                version_code = int(raw.get("versionCode", 0) or 0)
            except (TypeError, ValueError):
                version_code = 0
            first_lang = ""
            if sources and isinstance(sources[0], dict):
                first_lang = str(sources[0].get("language") or "")
            entries.append(RepoExtension(
                name=raw.get("name", pkg),
                pkg=pkg,
                lang=first_lang or "all",
                version=str(raw.get("versionName", "")),
                version_code=version_code,
                nsfw="NSFW" in str(raw.get("contentWarning", "")).upper(),
                repo_base=repo_base,
                apk_url=resources.get("apkUrl", ""),
                jar_url=resources.get("jarUrl", ""),
                icon_url=resources.get("iconUrl", ""),
                sources=sources,
            ))
        return entries

    def _parse_legacy(self, payload: list, repo_base: str) -> List[RepoExtension]:
        entries: List[RepoExtension] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            pkg = raw.get("pkg") or ""
            apk = raw.get("apk") or ""
            if not pkg or not apk:
                continue
            try:
                version_code = int(raw.get("code", 0) or 0)
            except (TypeError, ValueError):
                version_code = 0
            entries.append(RepoExtension(
                name=raw.get("name", pkg),
                pkg=pkg,
                lang=raw.get("lang", "all"),
                version=str(raw.get("version", "")),
                version_code=version_code,
                nsfw=bool(raw.get("nsfw", 0)),
                repo_base=repo_base,
                apk_url=f"{repo_base}/apk/{apk}",
                icon_url=f"{repo_base}/icon/{pkg}.png",
                sources=raw.get("sources", []) or [],
            ))
        return entries

    def fetch_all(self, force: bool = False) -> List[RepoExtension]:
        """Index of every configured repo, later repos overriding earlier by pkg."""
        merged: Dict[str, RepoExtension] = {}
        for repo in self._repos:
            for ext in self.fetch_index(repo, force=force):
                merged[ext.pkg] = ext
        return sorted(merged.values(), key=lambda e: e.display_name.lower())

    # ── Install / update state ────────────────────────────────────────────

    def installed_versions(self) -> Dict[str, int]:
        """Map package name -> installed versionCode, from ExtensionManager."""
        from .extension_manager import get_extension_manager

        versions: Dict[str, int] = {}
        for meta in get_extension_manager().get_installed_metadata().values():
            pkg = meta.get("package")
            if pkg:
                versions[pkg] = int(meta.get("version_code", 0) or 0)
        return versions

    def update_available(self, entries: Iterable[RepoExtension]) -> List[RepoExtension]:
        installed = self.installed_versions()
        return [e for e in entries if e.pkg in installed and e.version_code > installed[e.pkg]]

    # ── Downloads ─────────────────────────────────────────────────────────

    def download_artifact(
        self,
        ext: RepoExtension,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> Optional[tuple]:
        """
        Download the best available artifact for an extension.

        Returns ``(path, kind)`` where kind is ``"jar"`` or ``"apk"``. A prebuilt
        JAR is preferred: it loads straight into the bridge and avoids dex2jar,
        which is the step most likely to fail on an unusual APK.
        """
        if ext.prefers_jar:
            path = self._download(ext.jar_url, ext.pkg, ".jar", progress)
            if path:
                return path, "jar"
            logger.warning(f"{ext.display_name}: JAR download failed, falling back to APK")
        if ext.apk_url:
            path = self._download(ext.apk_url, ext.pkg, ".apk", progress)
            if path:
                return path, "apk"
        return None

    def _download(
        self,
        url: str,
        pkg: str,
        suffix: str,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> Optional[str]:
        session = create_http_session()
        try:
            response = session.get(url, timeout=180, stream=True)
            if response.status_code != 200:
                logger.error(f"HTTP {response.status_code} downloading {url}")
                return None

            total = int(response.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix=f"{pkg}-")
            with os.fdopen(fd, "wb") as fh:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total)

            if downloaded == 0:
                os.unlink(tmp_path)
                logger.error(f"Empty download for {url}")
                return None

            logger.info(f"Downloaded {pkg}{suffix} ({downloaded} bytes)")
            return tmp_path
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return None

    def download_icon(self, ext: RepoExtension) -> Optional[str]:
        """Fetch and cache the extension icon. Returns a local path."""
        target = ext.icon_path
        if target.exists() and target.stat().st_size > 0:
            return str(target)
        if not ext.icon_url:
            return None

        session = create_http_session()
        try:
            response = session.get(ext.icon_url, timeout=30)
            if response.status_code != 200:
                return None
            target.write_bytes(response.content)
            return str(target)
        except Exception as e:
            logger.debug(f"No icon for {ext.pkg}: {e}")
            return None


def get_repo_manager() -> RepoManager:
    return RepoManager.get_instance()
