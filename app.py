import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Arcade Game Picker", layout="centered")

st.title("🕹️ Arcade Game Picker (1978–2008)")
st.caption(
    "Filter, pick random, list results, favorite games, search by name, and see a Game of the Day. "
    "CSV caching is disabled so data updates take effect immediately. "
    "Game details & images can be loaded on-demand from adb.arcadeitalia.net."
)

# ----------------------------
# Constants
# ----------------------------
TZ = ZoneInfo("America/New_York")
APP_VERSION = "1.4 + ADB on-demand + server-side favorites + no caching"

CSV_PATH = "arcade_games_1978_2008_clean.csv"

# Favorites directory (server-side JSON)
FAV_DIR = Path(".favorites")
FAV_DIR.mkdir(exist_ok=True)


# ----------------------------
# Helpers: normalization / dataset
# ----------------------------
def normalize_str(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["rom", "game", "year", "company", "genre", "platform"]:
        if col not in df.columns:
            df[col] = ""

    df["rom"] = df["rom"].map(normalize_str).str.lower()
    df["game"] = df["game"].map(normalize_str)
    df["company"] = df["company"].map(normalize_str)
    df["genre"] = df["genre"].map(normalize_str)
    df["platform"] = df["platform"].map(normalize_str)

    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["game", "year"]).copy()
    df["year"] = df["year"].astype(int)
    return df


def load_games_no_cache() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH)
    return ensure_columns(df)


def build_links(game_name: str):
    q = game_name.replace(" ", "+")
    return {
        "Gameplay (YouTube)": f"https://www.youtube.com/results?search_query={q}+arcade",
        "MAME info (search)": f"https://www.google.com/search?q={q}+MAME",
        "History (search)": f"https://www.google.com/search?q={q}+arcade+history",
    }


# ----------------------------
# Favorites (server-side JSON)
# ----------------------------
def init_state():
    if "show_list" not in st.session_state:
        st.session_state.show_list = False
    if "favorites" not in st.session_state:
        st.session_state.favorites = []
    if "device_name" not in st.session_state:
        st.session_state.device_name = "default"
    if "favorites_loaded_for_device" not in st.session_state:
        st.session_state.favorites_loaded_for_device = None

    # ADB cache per session (avoid refetching same game repeatedly in one session)
    if "adb_cache" not in st.session_state:
        st.session_state.adb_cache = {}  # rom -> data dict (or {"_error": "..."})


def safe_device_name(device_name: str) -> str:
    s = (device_name or "").strip()
    s = "".join(ch for ch in s if ch.isalnum() or ch in ("-", "_")).strip()
    return s if s else "default"


def favorites_path(device_name: str) -> Path:
    safe = safe_device_name(device_name)
    return FAV_DIR / f"favorites_{safe}.json"


def load_favorites_from_disk(device_name: str) -> list[str]:
    p = favorites_path(device_name)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        favs = data.get("favorites", [])
        if isinstance(favs, list):
            return [str(x) for x in favs]
        return []
    except Exception:
        return []


def save_favorites_to_disk(device_name: str, favorites: list[str]) -> None:
    p = favorites_path(device_name)
    payload = {"favorites": favorites}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def game_key(row: pd.Series) -> str:
    rom = normalize_str(row.get("rom", "")).lower()
    if rom:
        return f"rom:{rom}"
    return f"meta:{normalize_str(row.get('game',''))}|{int(row.get('year',0))}|{normalize_str(row.get('company',''))}"


def is_favorited(key: str) -> bool:
    return key in st.session_state.favorites


def toggle_favorite(key: str):
    if key in st.session_state.favorites:
        st.session_state.favorites.remove(key)
    else:
        st.session_state.favorites.append(key)

    save_favorites_to_disk(st.session_state.device_name, st.session_state.favorites)


# ----------------------------
# ADB (Arcade Database / ArcadeItalia) on-demand integration
# ----------------------------
def adb_urls(rom: str):
    """
    ADB provides game pages accessible by rom short name.
    It also provides a scraper service endpoint used by front-ends/scrapers. :contentReference[oaicite:2]{index=2}
    SSL can be quirky sometimes, so we try https then http fallback. :contentReference[oaicite:3]{index=3}
    """
    rom = (rom or "").strip().lower()

    # Human-readable page
    page_https = f"https://adb.arcadeitalia.net/?mame={rom}"
    page_http = f"http://adb.arcadeitalia.net/?mame={rom}"

    # Scraper service endpoint (query by MAME short name / game_name)
    params = {"ajax": "query_mame", "lang": "en", "game_name": rom}
    scraper_https = "https://adb.arcadeitalia.net/service_scraper.php?" + urlencode(params)
    scraper_http = "http://adb.arcadeitalia.net/service_scraper.php?" + urlencode(params)

    return {
        "page_https": page_https,
        "page_http": page_http,
        "scraper_https": scraper_https,
        "scraper_http": scraper_http,
    }


def fetch_json_url(url: str, timeout_sec: int = 12) -> dict:
    """
    Minimal dependency HTTP fetch (urllib) so requirements stay tiny.
    Returns parsed JSON dict/list wrapped into a dict.
    """
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (ArcadeGamePicker/1.4; +https://streamlit.app)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace").strip()

    # Some services return JSON directly; others might return JSON as text.
    data = json.loads(text)

    # Normalize return to dict for easier handling
    if isinstance(data, dict):
        return data
    return {"_data": data}


def fetch_adb_details(rom: str) -> dict:
    """
    Try HTTPS scraper endpoint first, fall back to HTTP.
    Cache in session_state so repeated UI clicks are instant.
    """
    rom = (rom or "").strip().lower()
    if not rom:
        return {"_error": "No ROM short name available for this game."}

    if rom in st.session_state.adb_cache:
        return st.session_state.adb_cache[rom]

    urls = adb_urls(rom)

    last_err = None
    for u in (urls["scraper_https"], urls["scraper_http"]):
        try:
            data = fetch_json_url(u, timeout_sec=12)
            st.session_state.adb_cache[rom] = data
            return data
        except Exception as e:
            last_err = str(e)

    out = {
        "_error": "Could not retrieve data from ADB right now.",
        "_detail": last_err or "Unknown error",
        "_rom": rom,
        "_fallback_page": urls["page_http"],
    }
    st.session_state.adb_cache[rom] = out
    return out


def extract_image_urls(obj) -> list[str]:
    """
    Walk any dict/list structure and pull likely image URLs.
    We keep it conservative: only http(s) URLs ending in common image extensions.
    """
    urls = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            s = x.strip()
            if s.startswith("http://") or s.startswith("https://"):
                if re.search(r"\.(png|jpg|jpeg|webp)(\?.*)?$", s, re.IGNORECASE):
                    urls.append(s)

    walk(obj)

    # De-dupe while preserving order
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def show_adb_block(rom: str):
    """
    UI block: link + button to fetch + display details.
    """
    rom = (rom or "").strip().lower()
    if not rom:
        st.info("ADB details require a ROM short name; this entry has none.")
        return

    urls = adb_urls(rom)

    # Always show the ADB page link (prefer https, but http often works if ssl is finicky)
    st.markdown("**Arcade Database (ADB) links:**")
    st.write(f"- ADB page (HTTPS): {urls['page_https']}")
    st.write(f"- ADB page (HTTP fallback): {urls['page_http']}")

    col1, col2 = st.columns([1, 2])
    with col1:
        load_btn = st.button("📥 Load ADB details", key=f"adb_load_{rom}")
    with col2:
        show_images = st.toggle("Show images (if provided by ADB)", value=True, key=f"adb_img_{rom}")

    if not load_btn:
        return

    with st.spinner("Fetching from ADB..."):
        data = fetch_adb_details(rom)

    if isinstance(data, dict) and data.get("_error"):
        st.error(data["_error"])
        if data.get("_detail"):
            st.caption(f"Details: {data['_detail']}")
        st.caption("Tip: if this happens occasionally, it can be an ADB connectivity/SSL issue. Try the HTTP page link above.")
        return

    # Try to show a clean summary if common keys exist; otherwise show raw JSON
    st.subheader("ADB Details")

    # Common-ish keys (we don't assume all exist)
    candidate_keys = [
        "game_name",
        "title",
        "description",
        "manufacturer",
        "year",
        "genre",
        "players",
        "nplayers",
        "buttons",
        "controls",
        "control",
        "rotation",
        "sourcefile",
        "status",
        "category",
        "driver",
    ]

    displayed_any = False
    for k in candidate_keys:
        if k in data and data[k]:
            displayed_any = True
            val = data[k]
            if isinstance(val, (dict, list)):
                st.write(f"**{k}:**")
                st.json(val)
            else:
                st.write(f"**{k}:** {val}")

    if not displayed_any:
        st.caption("ADB returned data, but keys were not in the expected shape. Showing raw response.")
        st.json(data)

    if show_images:
        imgs = extract_image_urls(data)
        if imgs:
            st.subheader("ADB Images")
            # Keep it light: show the first few images if present
            for u in imgs[:6]:
                st.image(u, use_container_width=True)
        else:
            st.caption("No direct image URLs were found in the ADB response for this title.")


# ----------------------------
# Game details UI (includes ADB section)
# ----------------------------
def show_game_details(row: pd.Series, section_title: str = None):
    if row is None or len(row) == 0:
        return

    g = normalize_str(row.get("game", ""))
    y = int(row.get("year", 0))
    c = normalize_str(row.get("company", ""))
    genre = normalize_str(row.get("genre", ""))
    platform = normalize_str(row.get("platform", ""))
    rom = normalize_str(row.get("rom", "")).lower()

    if section_title:
        st.subheader(section_title)

    st.markdown(f"### {g}")
    st.write(f"**Year:** {y}")
    if c:
        st.write(f"**Company:** {c}")
    if genre:
        st.write(f"**Genre:** {genre}")
    if platform:
        st.write(f"**Platform:** {platform}")
    if rom:
        st.write(f"**ROM (MAME short name):** `{rom}`")

    key = game_key(row)

    colA, colB = st.columns([1, 2])
    with colA:
        label = "⭐ Unfavorite" if is_favorited(key) else "☆ Favorite"
        if st.button(label, key=f"favbtn_{key}_{section_title or 'details'}"):
            toggle_favorite(key)
            st.rerun()

    with colB:
        links = build_links(g)
        st.markdown("**Quick links:**")
        for name, url in links.items():
            st.write(f"- {name}: {url}")

    st.markdown("---")
    st.markdown("## 📚 Enhance with Arcade Database (ADB)")
    show_adb_block(rom)


# ----------------------------
# App state + data load (NO caching)
# ----------------------------
init_state()

try:
    df = load_games_no_cache()
except FileNotFoundError:
    st.error(f"Could not find {CSV_PATH} in the repo root. Upload it to GitHub and redeploy.")
    st.stop()
except Exception as e:
    st.error("Failed to load CSV.")
    st.code(str(e))
    st.stop()


# ----------------------------
# Sidebar: Persistent Favorites (Server-side JSON)
# ----------------------------
st.sidebar.header("⭐ Favorites (Persistent)")
st.sidebar.caption(f"Version {APP_VERSION}")

# Show CSV info (helps confirm you're using the latest)
try:
    p = Path(CSV_PATH)
    st.sidebar.caption(f"CSV rows: {len(df):,}")
    st.sidebar.caption(f"CSV modified (server): {datetime.fromtimestamp(p.stat().st_mtime)}")
except Exception:
    st.sidebar.caption("CSV info: unavailable")

device_input = st.sidebar.text_input(
    "Device name (separate favorites per device)",
    value=st.session_state.device_name,
    help="Example: andrew-ipad, andrew-laptop. Only letters/numbers/-/_ are kept.",
)

device = safe_device_name(device_input)
st.session_state.device_name = device

# Load favorites when device changes OR on first run
if st.session_state.favorites_loaded_for_device != device:
    st.session_state.favorites = load_favorites_from_disk(device)
    st.session_state.favorites_loaded_for_device = device

st.sidebar.write(f"Device: **{device}**")
st.sidebar.write(f"Favorites saved: **{len(st.session_state.favorites)}**")

col_s1, col_s2 = st.sidebar.columns(2)
with col_s1:
    if st.sidebar.button("💾 Save now"):
        save_favorites_to_disk(device, st.session_state.favorites)
        st.sidebar.success("Saved!")
with col_s2:
    if st.sidebar.button("🗑️ Clear"):
        st.session_state.favorites = []
        save_favorites_to_disk(device, st.session_state.favorites)
        st.sidebar.success("Cleared!")
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption("Favorites are stored server-side in .favorites/*.json (no uploads).")


# ----------------------------
# Search by Name (global)
# ----------------------------
st.header("🔎 Search by Game Name")
search_name = st.text_input("Type a game name (e.g., 'Out Run', 'Street Fighter', 'Pac-Man')", "")

if search_name.strip():
    s = search_name.strip().lower()
    matches = df[df["game"].astype(str).str.lower().str.contains(s)].copy()
    matches = matches.sort_values(["year", "game"]).head(200).reset_index(drop=True)

    if len(matches) == 0:
        st.info("No matches found. Try a shorter search (e.g., 'run', 'fighter', 'metal').")
    else:
        labels = (
            matches["game"].astype(str)
            + " — "
            + matches["year"].astype(str)
            + " — "
            + matches["company"].astype(str)
        )
        selected = st.selectbox("Matching games (select one)", labels, key="search_select")
        sel_idx = labels[labels == selected].index[0]
        sel_row = matches.loc[sel_idx]

        if st.button("📌 Show details for searched game"):
            show_game_details(sel_row, section_title="Search Result")

st.divider()


# ----------------------------
# Filters
# ----------------------------
st.header("Filters")

years = st.slider("Year range", 1978, 2008, (1978, 2008))

platforms = sorted(df["platform"].replace("", pd.NA).dropna().unique().tolist())
genres = sorted(df["genre"].replace("", pd.NA).dropna().unique().tolist())

col1, col2 = st.columns(2)
with col1:
    platform_choice = st.multiselect("Platform (optional)", platforms)
with col2:
    genre_choice = st.multiselect("Genre (optional)", genres)

filtered = df[(df["year"] >= years[0]) & (df["year"] <= years[1])].copy()
if platform_choice:
    filtered = filtered[filtered["platform"].isin(platform_choice)]
if genre_choice:
    filtered = filtered[filtered["genre"].isin(genre_choice)]

filtered = filtered.sort_values(["year", "game"]).reset_index(drop=True)
st.write(f"Games available: **{len(filtered):,}**")


# ----------------------------
# Game of the Day (stable daily change)
# ----------------------------
st.header("📆 Game of the Day")

now = datetime.now(TZ)
seed = int(now.strftime("%Y")) * 1000 + int(now.strftime("%j"))  # year + day-of-year

if len(filtered) == 0:
    st.warning("No games match your filters. Widen them to get a Game of the Day.")
else:
    gotd_idx = seed % len(filtered)
    gotd = filtered.iloc[gotd_idx]
    show_game_details(gotd, section_title=f"Game of the Day ({now.strftime('%b %d, %Y')})")

st.divider()


# ----------------------------
# Discover: Random + List
# ----------------------------
st.header("Discover")

btn1, btn2 = st.columns(2)
with btn1:
    pick_random = st.button("🎲 Pick a Random Game")
with btn2:
    if st.button("📜 Show/Hide List"):
        st.session_state.show_list = not st.session_state.show_list

if pick_random:
    if len(filtered) == 0:
        st.warning("No games match your filters. Try widening them.")
    else:
        pick = filtered.sample(1).iloc[0]
        show_game_details(pick, section_title="Random Pick")


# ----------------------------
# List + Select for details
# ----------------------------
if st.session_state.show_list:
    st.header("📜 Matching Games")

    search = st.text_input("Search within results (optional)", "")
    view = filtered[["rom", "game", "year", "company", "genre", "platform"]].copy()

    if search.strip():
        s = search.strip().lower()
        view = view[
            view["game"].astype(str).str.lower().str.contains(s)
            | view["company"].astype(str).str.lower().str.contains(s)
            | view["genre"].astype(str).str.lower().str.contains(s)
            | view["platform"].astype(str).str.lower().str.contains(s)
            | view["rom"].astype(str).str.lower().str.contains(s)
        ].copy()

    st.write(f"Showing: **{len(view):,}** games")
    st.dataframe(view, use_container_width=True, height=420)

    st.divider()
    st.subheader("🔎 Select a game from the list to see details")

    if len(view) == 0:
        st.info("No games to select. Widen filters or clear the search box.")
    else:
        view = view.reset_index(drop=True)
        labels = (
            view["game"].astype(str)
            + " — "
            + view["year"].astype(str)
            + " — "
            + view["company"].astype(str)
        )

        selected_label = st.selectbox("Select a game", labels, key="list_select")
        selected_idx = labels[labels == selected_label].index[0]
        selected_row = view.loc[selected_idx]

        if st.button("📌 Show selected game details"):
            show_game_details(selected_row, section_title="Selected Game")

    csv_bytes = view.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download this filtered list (CSV)",
        data=csv_bytes,
        file_name="arcade_filtered_games.csv",
        mime="text/csv",
    )


# ----------------------------
# Favorites view
# ----------------------------
st.header("⭐ Favorites")

if len(st.session_state.favorites) == 0:
    st.info("No favorites yet. Use ☆ Favorite on a game to add it.")
else:
    fav_rows = []
    fav_set = set(st.session_state.favorites)

    for _, row in df.iterrows():
        k = game_key(row)
        if k in fav_set:
            fav_rows.append(row)

    if len(fav_rows) == 0:
        st.warning("Favorites exist, but they couldn't be matched to the current dataset.")
    else:
        fav_df = pd.DataFrame(fav_rows)
        fav_df = fav_df[["rom", "game", "year", "company", "genre", "platform"]].sort_values(["year", "game"])
        st.dataframe(fav_df, use_container_width=True, height=320)
