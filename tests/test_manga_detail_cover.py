"""
Regression test for manga_detail.py's cover loading.

cover_local_path is a filesystem path, not a URL. Passing it straight to
image_loader.load_image_async() (which treats its argument as a fetchable
URL) makes curl reject it once the file no longer exists on disk - a stale
DB record after a manual cache clear, or after disk_cache pruning a file
whose path was already recorded. widgets.py already got this right (checks
existence, falls back to load_local_image); manga_detail.py did not.
"""
import unittest
from unittest.mock import patch

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

Gtk.init_check()
Adw.init()

from mihon.ui.manga_detail import MangaDetailView
from mihon.core.models import Manga


class CoverLoadingTests(unittest.TestCase):
    """
    load_manga() also kicks off _load_details(), which looks up a real
    extension and fetches over the network in a background thread. None of
    these manga are real, so get_registry() is patched to return nothing -
    _load_details() takes its own "no extension" early-return, and nothing
    here touches the network or writes into the real database.
    """

    def setUp(self):
        self.view = MangaDetailView()
        patcher = patch("mihon.ui.manga_detail.get_registry")
        self.addCleanup(patcher.stop)
        get_registry = patcher.start()
        get_registry.return_value.get.return_value = None

    def test_a_missing_local_path_falls_back_to_cover_url(self):
        manga = Manga(
            id=1, source_id="mangadex", title="Stale Cover",
            cover_local_path="/tmp/does-not-exist-cover-path-xyz",
            cover_url="https://uploads.mangadex.org/covers/fake/fake.jpg",
        )
        with patch("mihon.ui.manga_detail.image_loader.load_image_async") as async_load:
            with patch("mihon.ui.manga_detail.image_loader.load_local_image") as local_load:
                self.view.load_manga(manga)
        async_load.assert_called_once()
        self.assertEqual(async_load.call_args.args[0], manga.cover_url)
        local_load.assert_not_called()

    def test_an_existing_local_path_is_read_directly_not_fetched(self):
        manga = Manga(
            id=2, source_id="local", title="Local Cover",
            cover_local_path=__file__,  # any real file on disk
            cover_url="",
        )
        with patch("mihon.ui.manga_detail.image_loader.load_image_async") as async_load:
            with patch("mihon.ui.manga_detail.image_loader.load_local_image") as local_load:
                local_load.return_value = None
                self.view.load_manga(manga)
        local_load.assert_called_once()
        self.assertEqual(local_load.call_args.args[0], manga.cover_local_path)
        async_load.assert_not_called()

    def test_no_cover_at_all_does_not_call_either_loader(self):
        manga = Manga(id=3, source_id="mangadex", title="No Cover", cover_url="", cover_local_path=None)
        with patch("mihon.ui.manga_detail.image_loader.load_image_async") as async_load:
            with patch("mihon.ui.manga_detail.image_loader.load_local_image") as local_load:
                self.view.load_manga(manga)
        async_load.assert_not_called()
        local_load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
