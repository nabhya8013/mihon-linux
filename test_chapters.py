from mihon.extensions.jvm_bridge import get_bridge


def main():
    bridge = get_bridge()
    if not bridge.start():
        print("Failed to start JVM bridge")
        return

    try:
        # 1. Get popular manga list
        print("Fetching popular...")
        try:
            pop = bridge.call("extension.popular", {"extensionId": 1, "page": 1})
        except Exception as e:
            print("Popular request failed (extension may not be loaded):", e)
            return
        mangas = pop.get("mangas", [])
        if not mangas:
            print("No mangas found")
            return

        manga = mangas[0]
        manga_url = manga.get("url")
        print(f"First manga url: {manga_url}")

        # 2. Get details
        print("Fetching details...")
        det = bridge.call("extension.details", {"extensionId": 1, "mangaUrl": manga_url})
        print(f"Details: {det.get('title')}, {det.get('status')}")

        # 3. Get chapters
        print("Fetching chapters...")
        try:
            chaps = bridge.call("extension.chapters", {"extensionId": 1, "mangaUrl": manga_url})
            print(f"Found {len(chaps)} chapters.")
            if chaps:
                print("First chapter:", chaps[0])
        except Exception as e:
            print("Error getting chapters:", e)
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
