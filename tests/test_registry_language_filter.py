"""
Tests for ExtensionRegistry's language filter.

A single upstream jar can register one source per UI language it supports -
Tachiyomi/Mihon's real MangaDex extension alone provides 61, all displayed
as plain "MangaDex" with no distinguishing suffix. _language_allowed() reads
the real database.get_db() singleton, so each test gets an isolated DB via a
fresh XDG_DATA_HOME and module reload - the same pattern used in
test_database_concurrency.py, test_downloader.py and test_library_updater.py.
"""
import importlib
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


def _fresh_registry_module():
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp()
    from mihon.core import database
    importlib.reload(database)
    from mihon.extensions import registry
    importlib.reload(registry)
    return registry


def _fake_proxy(name: str, language: str, ext_id: str):
    proxy = MagicMock()
    proxy.id = ext_id
    proxy.name = name
    proxy.info = MagicMock(name=name, language=language)
    proxy.info.name = name
    proxy.info.language = language
    return proxy


class LanguageAllowedTests(unittest.TestCase):

    def setUp(self):
        self.registry_mod = _fresh_registry_module()
        self.registry = self.registry_mod.ExtensionRegistry.__new__(
            self.registry_mod.ExtensionRegistry
        )
        self.registry._extensions = {}
        self.registry._jvm_loaded = False

    def test_default_filter_allows_english(self):
        self.assertTrue(self.registry._language_allowed("en"))

    def test_default_filter_rejects_other_languages(self):
        self.assertFalse(self.registry._language_allowed("ja"))
        self.assertFalse(self.registry._language_allowed("id"))
        self.assertFalse(self.registry._language_allowed("ru"))

    def test_language_agnostic_sources_are_never_filtered(self):
        self.assertTrue(self.registry._language_allowed("all"))
        self.assertTrue(self.registry._language_allowed(""))

    def test_a_custom_filter_setting_is_respected(self):
        from mihon.core.database import get_db
        get_db().set_setting("extension_language_filter", json.dumps(["en", "ja"]))
        self.assertTrue(self.registry._language_allowed("en"))
        self.assertTrue(self.registry._language_allowed("ja"))
        self.assertFalse(self.registry._language_allowed("ru"))


class RegisterAndLoadJvmTests(unittest.TestCase):

    def setUp(self):
        self.registry_mod = _fresh_registry_module()
        self.registry = self.registry_mod.ExtensionRegistry.__new__(
            self.registry_mod.ExtensionRegistry
        )
        self.registry._extensions = {}
        self.registry._jvm_loaded = False

    def test_register_skips_a_non_english_source(self):
        self.registry.register(_fake_proxy("VoraToon", "id", "jvm_1"))
        self.assertEqual(self.registry.get_all(), [])

    def test_register_keeps_an_english_source(self):
        proxy = _fake_proxy("Mangahere", "en", "jvm_2")
        self.registry.register(proxy)
        self.assertEqual(self.registry.get_all(), [proxy])

    def test_load_jvm_extensions_filters_a_multi_language_jar_to_english(self):
        proxies = [
            _fake_proxy("MangaDex", "en", "jvm_en"),
            _fake_proxy("MangaDex", "ja", "jvm_ja"),
            _fake_proxy("MangaDex", "fr", "jvm_fr"),
            _fake_proxy("Rawkuma", "ja", "jvm_rawkuma"),
        ]
        # load_jvm_extensions() does `from .extension_manager import
        # get_extension_manager` locally on each call, so the source module's
        # name is what needs patching, not anything on the registry module.
        with patch("mihon.extensions.extension_manager.get_extension_manager") as get_manager:
            get_manager.return_value.load_all_installed.return_value = proxies
            self.registry.load_jvm_extensions()

        kept = {e.info.language for e in self.registry.get_all()}
        self.assertEqual(kept, {"en"})
        self.assertEqual(len(self.registry.get_all()), 1)
        self.assertTrue(self.registry._jvm_loaded)

    def test_load_jvm_extensions_only_runs_once(self):
        self.registry._jvm_loaded = True
        with patch("mihon.extensions.extension_manager.get_extension_manager") as get_manager:
            self.registry.load_jvm_extensions()
        get_manager.assert_not_called()


if __name__ == "__main__":
    unittest.main()
