import os
import zipfile
import subprocess
import shutil
import urllib.request
import logging
from pathlib import Path

logger = logging.getLogger("apk_extractor")

DEX2JAR_URL = "https://github.com/pxb1988/dex2jar/releases/download/v2.4/dex-tools-v2.4.zip"
TOOLS_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "mihon-linux" / "tools"

def ensure_dex2jar() -> Path:
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
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(TOOLS_DIR)
        
    os.remove(zip_path)
    
    # Make all .sh files executable
    for f in d2j_dir.glob("*.sh"):
        f.chmod(0o755)
        
    return d2j_sh

def extract_apk_and_convert(apk_path: str, output_dir: str):
    apk_path = Path(apk_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Read metadata from AndroidManifest.xml using androguard
    try:
        try:
            from androguard.core.apk import APK  # androguard 4.x
        except ImportError:
            from androguard.core.bytecodes.apk import APK  # androguard 3.x
        apk = APK(str(apk_path))
        
        # Mihon extensions declare the main class in an AndroidManifest meta-data tag: tachiyomi.extension.class
        manifest = apk.get_android_manifest_xml()
        
        extension_class = None
        extension_version = apk.get_androidversion_name() or "1.0"
        package_name = apk.get_package() or ""
        
        app_node = manifest.find('application')
        if app_node is not None:
            for meta in app_node.findall('meta-data'):
                name = meta.get('{http://schemas.android.com/apk/res/android}name')
                value = meta.get('{http://schemas.android.com/apk/res/android}value')
                if name == "tachiyomi.extension.class":
                    extension_class = value
                    
        app_name = apk.get_app_name()
        
        if not extension_class:
            logger.error(f"Could not find tachiyomi.extension.class in {apk_path}")
            return None

        # Resolve relative class names (e.g. ".Mangago" → "eu.kanade.tachiyomi.revived.en.mangago.Mangago")
        # Also handles semicolon-separated multi-source entries
        resolved_classes = []
        for cls in extension_class.split(";"):
            cls = cls.strip()
            if not cls:
                continue
            if cls.startswith("."):
                cls = package_name + cls
            resolved_classes.append(cls)
        extension_class = ";".join(resolved_classes)
            
        logger.info(f"Found Extension Class: {extension_class}")
        
    except ImportError:
        logger.error("androguard package is not installed. Run 'pip install androguard'")
        return None
    except Exception as e:
        logger.error(f"Failed to parse APK: {e}")
        return None
        
    # 2. Extract classes.dex
    dex_path = output_dir / "classes.dex"
    try:
        with zipfile.ZipFile(apk_path, 'r') as apk_zip:
            if 'classes.dex' not in apk_zip.namelist():
                logger.error("No classes.dex found in APK.")
                return None
            with apk_zip.open('classes.dex') as source, open(dex_path, 'wb') as target:
                shutil.copyfileobj(source, target)
    except Exception as e:
        logger.error(f"Failed to extract dex: {e}")
        return None
        
    # 3. Convert dex to jar
    try:
        d2j_sh = ensure_dex2jar()
    except Exception:
        return None
        
    out_jar = output_dir / f"{apk_path.stem}.jar"
    
    logger.info("Converting dex to jar...")
    try:
        subprocess.run(
            [str(d2j_sh), "--force", "-o", str(out_jar), str(dex_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"dex2jar failed: {e.stderr.decode()}")
        return None
        
    # Optional cleanup of classes.dex
    if dex_path.exists():
        dex_path.unlink()
        
    return {
        "jar_path": str(out_jar),
        "source_class": extension_class,
        "name": app_name,
        "version": extension_version
    }
