import sys
import json
from mihon.extensions.jvm_bridge import get_bridge

def main():
    bridge = get_bridge()
    bridge.start()
    
    # 1. Get popular manga list
    print("Fetching popular...")
    pop = bridge.call("extension.popular", {"extensionId": 1, "page": 1})
    mangas = pop.get("mangas", [])
    if not mangas:
        print("No mangas found")
        return
        
    manga = mangas[0]
    mangaUrl = manga.get("url")
    print(f"First manga url: {mangaUrl}")
    
    # 2. Get details
    print("Fetching details...")
    det = bridge.call("extension.details", {"extensionId": 1, "mangaUrl": mangaUrl})
    print(f"Details: {det.get('title')}, {det.get('status')}")
    
    # 3. Get chapters
    print("Fetching chapters...")
    try:
        chaps = bridge.call("extension.chapters", {"extensionId": 1, "mangaUrl": mangaUrl})
        print(f"Found {len(chaps)} chapters.")
        if chaps:
            print("First chapter:", chaps[0])
    except Exception as e:
        print("Error getting chapters:", e)
        
    bridge._process.terminate()

if __name__ == "__main__":
    main()
