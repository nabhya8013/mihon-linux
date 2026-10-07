"""
Guards for the Flatpak packaging files.

A Flatpak build has no network, so every Python dependency is pinned by hash in
data/python3-requirements.json. These checks catch the two ways that drifts
silently: requirements.txt gaining a package the module lacks, and a pin
losing its hash or turning into a source build.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "io.github.nabhya8013.MihonLinux.yml"
MODULE = ROOT / "data" / "python3-requirements.json"
# The GNOME runtime provides PyGObject.
PROVIDED_BY_RUNTIME = {"pygobject"}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_names():
    names = set()
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(_normalize(re.split(r"[<>=!~\[;\s]", line, maxsplit=1)[0]))
    return names - PROVIDED_BY_RUNTIME


class FlatpakPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = json.loads(MODULE.read_text())
        cls.manifest = MANIFEST.read_text()

    def test_every_requirement_has_a_pinned_module(self):
        pinned = {_normalize(m["name"].removeprefix("python3-")) for m in self.module["modules"]}
        missing = _requirement_names() - pinned
        self.assertFalse(
            missing,
            f"requirements.txt packages missing from {MODULE.name}: {sorted(missing)}. "
            "Regenerate it (command in the manifest header).",
        )

    def test_every_source_is_a_hashed_wheel(self):
        for module in self.module["modules"]:
            for source in module["sources"]:
                name = source["url"].rsplit("/", 1)[1]
                self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$", name)
                self.assertTrue(
                    name.endswith(".whl"),
                    f"{name} is a source distribution; the sandbox build cannot compile it",
                )

    def test_manifest_includes_the_pinned_module(self):
        self.assertIn("- python3-requirements.json", self.manifest)

    def test_manifest_launcher_exists_and_is_executable_in_the_sandbox(self):
        launcher = ROOT / "data" / "mihon-linux-flatpak.sh"
        self.assertTrue(launcher.is_file())
        self.assertIn("/app/share/mihon-linux-app/run.py", launcher.read_text())
        self.assertIn("data/mihon-linux-flatpak.sh", self.manifest)

    def test_package_lands_under_its_own_name(self):
        # `cp -r mihon <existing-dir>` would drop the package name and break
        # `import mihon`, so the manifest must spell out the target.
        self.assertIn("share/mihon-linux-app/mihon", self.manifest)

    def test_runtime_is_not_end_of_life(self):
        match = re.search(r'runtime-version:\s*"(\d+)"', self.manifest)
        self.assertIsNotNone(match)
        self.assertGreaterEqual(int(match.group(1)), 49)


if __name__ == "__main__":
    unittest.main()
