from mihon.extensions.mangadex import MangaDexExtension
from mihon.core.models import Manga, SearchFilter

ext = MangaDexExtension()
print("Searching...")
mangas, _ = ext.search(SearchFilter(query="more than a married couple but not lovers"))
if not mangas:
    print("No results returned (network/source may be unavailable).")
    raise SystemExit(0)
m = mangas[0]
print("Found manga:", m.title, m.source_manga_id)

print("Getting details...")
m_details = ext.get_manga_details(m)
print("Details:", m_details.description[:50])

print("Getting chapters...")
chapters = ext.get_chapters(m)
print("Found chapters:", len(chapters))
if chapters:
    print("Chapter 0:", chapters[0].title)
