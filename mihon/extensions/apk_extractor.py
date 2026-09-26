"""
APK extension extractor.

Converts a Tachiyomi/Mihon extension `.apk` into a JAR the JVM bridge can load,
and pulls the extension metadata out of AndroidManifest.xml.

dex2jar is handed the APK directly rather than a single `classes.dex`, so
multidex extensions (`classes2.dex`, `classes3.dex`, ...) convert correctly.
"""
import os
import zipfile
import subprocess
import shutil
import urllib.request
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("apk_extractor")

DEX2JAR_URL = "https://github.com/pxb1988/dex2jar/releases/download/v2.4/dex-tools-v2.4.zip"
TOOLS_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "mihon-linux" / "tools"

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

# AndroidManifest meta-data keys used by Tachiyomi/Mihon extensions.
META_CLASS = "tachiyomi.extension.class"
META_NSFW = "tachiyomi.extension.nsfw"
META_HAS_README = "tachiyomi.extension.hasReadme"
META_HAS_CHANGELOG = "tachiyomi.extension.hasChangelog"


def ensure_dex2jar() -> Path:
    """Download dex2jar on first use; return the path to d2j-dex2jar.sh."""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    d2j_dir = TOOLS_DIR / "dex-tools-v2.4"
    d2j_sh = d2j_dir / "d2j-dex2jar.sh"

    if d2j_sh.exists():
        return d2j_sh

    logger.info("Downloading dex2jar...")
    zip_path = TOOLS_DIR / "dex2jar.zip"
    try:
        urllib.request.urlretrieve(DEX2JAR_URL, zip_path)
    except Exception as e:
        logger.error(f"Failed to download dex2jar: {e}")
        raise

    logger.info("Extracting dex2jar...")
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(TOOLS_DIR)

    os.remove(zip_path)

    for f in d2j_dir.glob("*.sh"):
        f.chmod(0o755)

    return d2j_sh


def _load_apk_class():
    """Import androguard's APK class across 3.x/4.x layouts."""
    try:
        from androguard.core.apk import APK  # androguard 4.x
        return APK
    except ImportError:
        from androguard.core.bytecodes.apk import APK  # androguard 3.x
        return APK


def _read_meta_data(apk) -> Dict[str, str]:
    """Collect every <meta-data> name/value under <application>."""
    meta: Dict[str, str] = {}
    try:
        manifest = apk.get_android_manifest_xml()
    except Exception as e:
        logger.warning(f"Could not read AndroidManifest.xml: {e}")
        return meta

    app_node = manifest.find("application")
    if app_node is None:
        return meta

    for node in app_node.findall("meta-data"):
        name = node.get(f"{ANDROID_NS}name")
        value = node.get(f"{ANDROID_NS}value")
        if name:
            meta[name] = value if value is not None else ""
    return meta


def _resolve_classes(raw: str, package_name: str) -> str:
    """Expand relative class names and normalise the ';'-separated list."""
    resolved = []
    for cls in raw.split(";"):
        cls = cls.strip()
        if not cls:
            continue
        if cls.startswith("."):
            cls = package_name + cls
        resolved.append(cls)
    return ";".join(resolved)


def _truthy(value: Optional[str]) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


def _extract_native_libs(apk_path: Path, dest: Path) -> Optional[str]:
    """
    Extract bundled `lib/<abi>/*.so` for the host architecture.

    Extensions that call System.loadLibrary need these on java.library.path.
    Returns the directory holding the .so files, or None when the APK has none.
    """
    import platform

    machine = platform.machine().lower()
    abi_preference = {
        "x86_64": ["x86_64", "x86"],
        "amd64": ["x86_64", "x86"],
        "aarch64": ["arm64-v8a", "armeabi-v7a"],
        "arm64": ["arm64-v8a", "armeabi-v7a"],
    }.get(machine, ["x86_64"])

    try:
        with zipfile.ZipFile(apk_path, "r") as apk_zip:
            names = apk_zip.namelist()
            for abi in abi_preference:
                members = [n for n in names if n.startswith(f"lib/{abi}/") and n.endswith(".so")]
                if not members:
                    continue
                lib_dir = dest / "lib"
                lib_dir.mkdir(parents=True, exist_ok=True)
                for member in members:
                    target = lib_dir / Path(member).name
                    with apk_zip.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                logger.info(f"Extracted {len(members)} native lib(s) for {abi}")
                return str(lib_dir)
    except Exception as e:
        logger.warning(f"Could not extract native libs: {e}")
    return None


def _count_dex(apk_path: Path) -> int:
    try:
        with zipfile.ZipFile(apk_path, "r") as apk_zip:
            return sum(
                1 for n in apk_zip.namelist()
                if n.startswith("classes") and n.endswith(".dex") and "/" not in n
            )
    except Exception:
        return 0


def extract_apk_and_convert(apk_path: str, output_dir: str) -> Optional[Dict[str, Any]]:
    """
    Convert an extension APK to a JAR and return its metadata.

    Returns None when the APK is not a usable Tachiyomi/Mihon extension.
    """
    apk_path = Path(apk_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not apk_path.is_file():
        logger.error(f"APK not found: {apk_path}")
        return None

    # ── 1. Manifest metadata ────────────────────────────────────────────
    try:
        APK = _load_apk_class()
    except ImportError:
        logger.error("androguard package is not installed. Run 'pip install androguard'")
        return None

    try:
        apk = APK(str(apk_path))
        package_name = apk.get_package() or ""
        extension_version = apk.get_androidversion_name() or "1.0"
        try:
            version_code = int(apk.get_androidversion_code() or 0)
        except (TypeError, ValueError):
            version_code = 0
        app_name = apk.get_app_name() or apk_path.stem
        meta = _read_meta_data(apk)
    except Exception as e:
        logger.error(f"Failed to parse APK {apk_path.name}: {e}")
        return None

    raw_class = meta.get(META_CLASS)
    if not raw_class:
        logger.error(
            f"{apk_path.name} declares no '{META_CLASS}' meta-data — "
            "not a Tachiyomi/Mihon extension APK."
        )
        return None

    extension_class = _resolve_classes(raw_class, package_name)
    if not extension_class:
        logger.error(f"'{META_CLASS}' in {apk_path.name} resolved to an empty class list.")
        return None

    nsfw = _truthy(meta.get(META_NSFW, "0"))
    dex_count = _count_dex(apk_path)
    logger.info(
        f"{app_name} v{extension_version} ({package_name}) — "
        f"{dex_count} dex, nsfw={nsfw}, classes: {extension_class}"
    )

    # ── 2. Convert the whole APK (handles multidex) ─────────────────────
    try:
        d2j_sh = ensure_dex2jar()
    except Exception:
        return None

    out_jar = output_dir / f"{apk_path.stem}.jar"
    logger.info("Converting APK to jar...")
    try:
        proc = subprocess.run(
            [str(d2j_sh), "--force", "-o", str(out_jar), str(apk_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
        )
        stderr = proc.stderr.decode(errors="replace").strip()
        if stderr:
            # dex2jar reports per-method translation failures on stderr but
            # still produces a usable jar; surface them without failing.
            logger.debug(f"dex2jar diagnostics: {stderr[:2000]}")
    except subprocess.TimeoutExpired:
        logger.error(f"dex2jar timed out converting {apk_path.name}")
        return None
    except subprocess.CalledProcessError as e:
        logger.error(f"dex2jar failed: {e.stderr.decode(errors='replace')[:2000]}")
        return None

    if not out_jar.is_file() or out_jar.stat().st_size == 0:
        logger.error(f"dex2jar produced no output for {apk_path.name}")
        return None

    # ── 3. Native libraries (optional) ──────────────────────────────────
    native_lib_dir = _extract_native_libs(apk_path, output_dir / apk_path.stem)

    return {
        "jar_path": str(out_jar),
        "source_class": extension_class,
        "name": app_name,
        "version": extension_version,
        "version_code": version_code,
        "package": package_name,
        "nsfw": nsfw,
        "native_lib_dir": native_lib_dir,
        "has_readme": _truthy(meta.get(META_HAS_README, "0")),
        "has_changelog": _truthy(meta.get(META_HAS_CHANGELOG, "0")),
    }
