from urllib.parse import quote_plus

def build_links_curated(game_name: str, rom: str | None):
    q_title = quote_plus(game_name)
    links = {
        "Arcade-Museum search (KLOV / Museum of the Game)": f"https://www.arcade-museum.com/search?term={q_title}",
    }

    # ADB (ROM-first)
    if rom:
        rom = rom.strip().lower()
        links["ADB (Arcade Database) page"] = f"https://adb.arcadeitalia.net/?mame={rom}"
        links["Arcade-Museum MAME database search"] = "https://www.arcade-museum.com/tech-center/mame"

    return links
