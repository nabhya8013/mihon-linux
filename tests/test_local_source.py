"""
Tests for the local CBZ/ZIP source.

Everything runs against a real temporary directory tree, so archive reading,
page ordering and cover discovery are exercised as shipped.
"""
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from mihon.core.models import Chapter, Manga, SearchFilter
from mihon.extensions.local import (
    LocalSource,
    is_archive,
    is_image,
    natural_key,
    parse_chapter_number,
)

# A one-pixel PNG, enough to be a real image file on disk.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


class FakeDB:
    def __init__(self):
        self.settings = {}

    def get_setting(self, key, default=""):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value


def _make_cbz(path: Path, names):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as bundle:
        for name in names:
            bundle.writestr(name, PNG)


class HelperTests(unittest.TestCase):

    def test_chapter_number_from_an_explicit_marker(self):
        self.assertEqual(parse_chapter_number("Chapter 12.cbz"), 12.0)
        self.assertEqual(parse_chapter_number("c012.cbz"), 12.0)
        self.assertEqual(parse_chapter_number("Ch. 7.5.cbz"), 7.5)

    def test_chapter_number_falls_back_to_the_last_number(self):
        self.assertEqual(parse_chapter_number("Series 03 - 014.cbz"), 14.0)

    def test_no_number_reports_minus_one(self):
        """Which is exactly the case source order exists for."""
        self.assertEqual(parse_chapter_number("Prologue.cbz"), -1.0)

    def test_natural_key_orders_numbers_numerically(self):
        names = ["10.jpg", "2.jpg", "1.jpg"]
        self.assertEqual(
            sorted(names, key=natural_key), ["1.jpg", "2.jpg", "10.jpg"]
        )

    def test_suffix_helpers(self):
        self.assertTrue(is_image(Path("a.WEBP")))
        self.assertFalse(is_image(Path("a.txt")))
        self.assertTrue(is_archive(Path("a.CBZ")))
        self.assertTrue(is_archive(Path("a.zip")))
        self.assertFalse(is_archive(Path("a.cbr")))


class LocalSourceTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Manga"
        self.root.mkdir()

        # A series of archives.
        _make_cbz(self.root / "Berserk" / "Chapter 1.cbz", ["002.png", "001.png", "010.png"])
        _make_cbz(self.root / "Berserk" / "Chapter 2.cbz", ["001.png"])
        (self.root / "Berserk" / "cover.png").write_bytes(PNG)

        # A series of loose image folders.
        volume = self.root / "Akira" / "Volume 01"
        volume.mkdir(parents=True)
        for name in ("001.png", "002.png"):
            (volume / name).write_bytes(PNG)

        self.db = FakeDB()
        self.source = LocalSource(db=self.db, root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    # ── Configuration ─────────────────────────────────────────────────────

    def test_the_configured_folder_is_read_from_settings(self):
        db = FakeDB()
        db.settings["local_source_dir"] = str(self.root)
        self.assertEqual(LocalSource(db=db).root, self.root)

    def test_set_root_persists_and_reports_existence(self):
        source = LocalSource(db=self.db)
        self.assertTrue(source.set_root(self.root))
        self.assertEqual(self.db.settings["local_source_dir"], str(self.root))
        self.assertFalse(source.set_root(self.root / "nope"))

    def test_a_missing_folder_lists_nothing_rather_than_raising(self):
        source = LocalSource(db=FakeDB(), root=self.root / "does-not-exist")
        self.assertEqual(source.get_popular()[0], [])

    # ── Browsing ──────────────────────────────────────────────────────────

    def test_each_folder_is_one_series(self):
        manga, has_next = self.source.get_popular()
        self.assertEqual([m.title for m in manga], ["Akira", "Berserk"])
        self.assertFalse(has_next)

    def test_series_carry_the_local_source_id(self):
        manga, _ = self.source.get_popular()
        self.assertTrue(all(m.source_id == "local" for m in manga))

    def test_series_are_already_initialized(self):
        """Nothing more can be learned by a details round trip."""
        manga, _ = self.source.get_popular()
        self.assertTrue(all(m.initialized for m in manga))

    def test_a_named_cover_is_used(self):
        manga, _ = self.source.get_popular()
        berserk = next(m for m in manga if m.title == "Berserk")
        self.assertTrue(berserk.cover_local_path.endswith("cover.png"))

    def test_the_first_page_is_the_cover_when_none_is_named(self):
        manga, _ = self.source.get_popular()
        akira = next(m for m in manga if m.title == "Akira")
        self.assertTrue(akira.cover_local_path.endswith("001.png"))

    def test_search_filters_by_title(self):
        found, _ = self.source.search(SearchFilter(query="ber"))
        self.assertEqual([m.title for m in found], ["Berserk"])

    def test_an_empty_search_returns_everything(self):
        found, _ = self.source.search(SearchFilter(query=""))
        self.assertEqual(len(found), 2)

    def test_hidden_folders_are_skipped(self):
        (self.root / ".hidden").mkdir()
        manga, _ = self.source.get_popular()
        self.assertNotIn(".hidden", [m.title for m in manga])

    # ── Chapters ──────────────────────────────────────────────────────────

    def test_archives_become_chapters(self):
        manga = Manga(source_id="local", source_manga_id="Berserk", id=1)
        chapters = self.source.get_chapters(manga)
        self.assertEqual([c.title for c in chapters], ["Chapter 2", "Chapter 1"])

    def test_chapter_numbers_are_parsed(self):
        manga = Manga(source_id="local", source_manga_id="Berserk", id=1)
        chapters = self.source.get_chapters(manga)
        self.assertEqual(sorted(c.chapter_number for c in chapters), [1.0, 2.0])

    def test_chapters_carry_source_order_newest_first(self):
        manga = Manga(source_id="local", source_manga_id="Berserk", id=1)
        chapters = self.source.get_chapters(manga)
        self.assertEqual(chapters[0].source_order, 0)
        self.assertEqual(chapters[0].title, "Chapter 2")

    def test_chapter_ids_are_relative_to_the_library_root(self):
        """So the id survives the library folder being moved."""
        manga = Manga(source_id="local", source_manga_id="Berserk", id=1)
        for chapter in self.source.get_chapters(manga):
            self.assertFalse(Path(chapter.source_chapter_id).is_absolute())

    def test_a_folder_of_images_is_a_chapter(self):
        manga = Manga(source_id="local", source_manga_id="Akira", id=1)
        chapters = self.source.get_chapters(manga)
        self.assertEqual([c.title for c in chapters], ["Volume 01"])

    def test_loose_images_in_a_series_folder_are_one_chapter(self):
        series = self.root / "Oneshot"
        series.mkdir()
        (series / "001.png").write_bytes(PNG)
        manga = Manga(source_id="local", source_manga_id="Oneshot", id=1)
        self.assertEqual(len(self.source.get_chapters(manga)), 1)

    def test_a_missing_series_has_no_chapters(self):
        manga = Manga(source_id="local", source_manga_id="Ghost", id=1)
        self.assertEqual(self.source.get_chapters(manga), [])

    # ── Pages ─────────────────────────────────────────────────────────────

    def test_archive_pages_are_extracted_in_natural_order(self):
        chapter = Chapter(source_chapter_id="Berserk/Chapter 1.cbz")
        pages = self.source.get_pages(chapter)
        self.assertEqual(len(pages), 3)
        # 001, 002, 010 — not the string order 001, 010, 002.
        self.assertEqual([p.index for p in pages], [0, 1, 2])
        for page in pages:
            self.assertTrue(Path(page.local_path).is_file())

    def test_folder_pages_are_read_directly(self):
        chapter = Chapter(source_chapter_id="Akira/Volume 01")
        pages = self.source.get_pages(chapter)
        self.assertEqual(len(pages), 2)
        self.assertTrue(pages[0].local_path.endswith("001.png"))

    def test_extraction_is_reused_on_a_second_read(self):
        chapter = Chapter(source_chapter_id="Berserk/Chapter 1.cbz")
        first = self.source.get_pages(chapter)
        second = self.source.get_pages(chapter)
        self.assertEqual(
            [p.local_path for p in first], [p.local_path for p in second]
        )

    def test_a_missing_chapter_yields_no_pages(self):
        self.assertEqual(
            self.source.get_pages(Chapter(source_chapter_id="Nope/None.cbz")), []
        )

    def test_a_corrupt_archive_yields_no_pages_rather_than_raising(self):
        bad = self.root / "Berserk" / "Broken.cbz"
        bad.write_bytes(b"not a zip file")
        self.assertEqual(
            self.source.get_pages(Chapter(source_chapter_id="Berserk/Broken.cbz")), []
        )

    def test_an_archive_with_no_images_yields_no_pages(self):
        path = self.root / "Berserk" / "Empty.cbz"
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("readme.txt", "nothing here")
        self.assertEqual(
            self.source.get_pages(Chapter(source_chapter_id="Berserk/Empty.cbz")), []
        )

    def test_macos_resource_forks_are_not_pages(self):
        path = self.root / "Berserk" / "Mac.cbz"
        _make_cbz(path, ["001.png", "__MACOSX/._001.png"])
        pages = self.source.get_pages(Chapter(source_chapter_id="Berserk/Mac.cbz"))
        self.assertEqual(len(pages), 1)

    def test_nested_archive_paths_stay_inside_the_staging_folder(self):
        """A archive entry must never write outside the extract directory."""
        from mihon.extensions.local import EXTRACT_DIR
        path = self.root / "Berserk" / "Nested.cbz"
        _make_cbz(path, ["deep/inner/001.png", "deep/inner/002.png"])
        pages = self.source.get_pages(Chapter(source_chapter_id="Berserk/Nested.cbz"))
        self.assertEqual(len(pages), 2)
        for page in pages:
            self.assertTrue(str(page.local_path).startswith(str(EXTRACT_DIR)))

    # ── Details ───────────────────────────────────────────────────────────

    def test_details_json_overrides_the_inferred_metadata(self):
        import json
        (self.root / "Berserk" / "details.json").write_text(json.dumps({
            "title": "Berserk (Deluxe)",
            "author": "Kentaro Miura",
            "genre": ["Action", "Dark Fantasy"],
            "status": "completed",
        }))
        manga = self.source.get_manga_details(
            Manga(source_id="local", source_manga_id="Berserk")
        )
        self.assertEqual(manga.title, "Berserk (Deluxe)")
        self.assertEqual(manga.author, "Kentaro Miura")
        self.assertEqual(manga.genres, ["Action", "Dark Fantasy"])

    def test_a_comma_separated_genre_string_is_accepted(self):
        import json
        (self.root / "Berserk" / "details.json").write_text(
            json.dumps({"genre": "Action, Horror"})
        )
        manga = self.source.get_manga_details(
            Manga(source_id="local", source_manga_id="Berserk")
        )
        self.assertEqual(manga.genres, ["Action", "Horror"])

    def test_a_malformed_details_file_is_ignored(self):
        (self.root / "Berserk" / "details.json").write_text("{ not json")
        manga = self.source.get_manga_details(
            Manga(source_id="local", source_manga_id="Berserk")
        )
        self.assertEqual(manga.title, "Berserk")

    def test_details_for_a_missing_series_returns_the_input(self):
        original = Manga(source_id="local", source_manga_id="Ghost", title="Ghost")
        self.assertIs(self.source.get_manga_details(original), original)


if __name__ == "__main__":
    unittest.main()
