from mihon.extensions.allmanga import AllMangaExtension
from mihon.core.models import Manga, SearchFilter

ext = AllMangaExtension()
# 1. search for a manga
print("Searching...")
mangas, _ = ext.search(SearchFilter(query="more than a married couple but not lovers"))
m=mangas[0]
print("Found manga:", m.title, m.source_manga_id)

# 2. get details
print("Getting details...")
m_details = ext.get_manga_details(m)
print("Details:", m_details.description[:50])

# 3. get chapters
print("Getting chapters...")
chapters = ext.get_chapters(m)
print("Found chapters:", len(chapters))
if chapters:
    print("Chapter 0:", chapters[0].title)

