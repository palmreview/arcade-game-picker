import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

# ----------------------------
# Page config
# ----------------------------
st.set_page_config(page_title="Arcade Game Picker", layout="wide")

st.title("🕹️ Arcade Game Picker (1978–2008)")
st.caption(
    "Cabinet-first discovery: find games you can actually play at home, learn the history, and see artwork. "
    "CSV caching is disabled so data updates apply immediately. ADB details/artwork load on-demand."
)

# ----------------------------
# Constants
# ----------------------------
TZ = ZoneInfo("America/New_York")
APP_VERSION = "1.5 (candidate baseline) • Strict Cabinet Mode • ADB on-demand • No caching"
CSV_PATH = "arcade_games_1978_2008_clean.csv"


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

    # convenience lower-case helpers (not shown)
    df["_game_l"] = df["game"].astype(str).str.lower()
    df["_genre_l"] = df["genre"].astype(str).str.lower()
    df["_platform_l"] = df["platform"].astype(str).str.lower()
    df["_company_l"] = df["company"].astype(str).str.lower()

    return df


def load_games_no_cache() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH)
    return ensure_columns(df)


def build_links(game_name: str):
    q = game_name.replace(" ", "+")
    return {
        "Gameplay (YouTube)": f"https://www.youtube.com/results?search_query={q}+arcade+gameplay",
        "History / Legacy (search)": f"https://www.google.com/search?q={q}+arcade+history+legacy",
        "Controls / Moves (search)": f"https://www.google.com/search?q={q}+arcade+controls+buttons",
        "Manual / Instructions (search)": f"https://www.google.com/search?q={q}+arcade+manual+instructions",
    }


def init_state():
    if "show_list" not in st.session_state:
        st.session_state.show_list = True
    if "picked_rows" not in st.session_state:
        st.session_state.picked_rows = []  # for "10 picks"
    if "selected_key" not in st.session_state:
        st.session_state.selected_key = None
    if "adb_cache" not in st.session_state:
        st.session_state.adb_cache = {}  # rom -> dict or {"_error": ...}
    if "last_selected_rom" not in st.session_state:
        st.session_state.last_selected_rom = ""


def game_key(row: pd.Series) -> str:
    rom = normalize_str(row.get("rom", "")).lower()
    if rom:
        return f"rom:{rom}"
    return f"meta:{normalize_str(row.get('game',''))}|{int(row.get('year',0))}|{normalize_str(row.get('company',''))}"


# ----------------------------
# Cabinet profile + strict compatibility
# ----------------------------
CABINET = {
    "has_4way": True,
    "has_8way": True,
    "buttons_per_player": 6,
    "has_spinner": False,
    "has_trackball": False,
    "has_lightgun": False,
    "has_wheel": False,
    "horizontal_monitor": True,
    "vertical_ok": True,
}

# These are *strict* exclusions based on your hardware.
# We use your CSV genre + a bit of title heuristics to block clearly incompatible sets.
BLOCKED_GENRE_EXACT = {
    "trackball",
    "dial/paddle",
    "dial",
    "paddle",
    "lightgun shooter",
    "gambling",
    "casino",
    "quiz",
}

# Common genre names vary by dataset; these are conservative for "wheel/pedals" type games.
BLOCKED_GENRE_CONTAINS = [
    "driving",
    "racing",
    "pinball",  # usually special controls
    "redemption",  # ticket/redemption often special
    "mahjong",  # optional; comment out if you want mahjong video games
]

# Title keywords (only used as an extra safety net)
BLOCKED_TITLE_HINTS = [
    "gun",
    "light gun",
    "lightgun",
    "wheel",
    "steering",
    "pedal",
    "paddle",
    "trackball",
    "spinner",
]


def is_cabinet_compatible_strict(row: pd.Series) -> bool:
    """
    Strict mode means "only show what you can play on your cabinet".
    We rely on local dataset fields; ADB is used for details/controls, not for filtering the whole catalog.
    """
    genre = normalize_str(row.get("genre", "")).strip().lower()
    title = normalize_str(row.get("game", "")).strip().lower()
    platform = normalize_str(row.get("platform", "")).strip().lower()

    if not genre and not title:
        return False

    # Exclude obvious non-video or unwanted categories (some may already be cleaned out)
    if genre in BLOCKED_GENRE_EXACT:
        return False

    for frag in BLOCKED_GENRE_CONTAINS:
        if frag in genre:
            return False

    # If platform contains these (rare), block
    if any(x in platform for x in ("gambling", "casino", "slot", "quiz")):
        return False

    # Title hint safety net (won't catch everything, but avoids obvious mismatches)
    for hint in BLOCKED_TITLE_HINTS:
        if hint in title:
            return False

    return True


def cabinet_fit_badges(row: pd.Series, adb: dict | None) -> list[str]:
    """
    Return UI badges (strings). Uses ADB if loaded; falls back to CSV.
    """
    badges = []

    # From CSV
    genre = normalize_str(row.get("genre", ""))
    if genre:
        badges.append(f"Genre: {genre}")

    # From ADB if present
    if adb and isinstance(adb, dict) and not adb.get("_error"):
        # players
        for k in ("players", "nplayers", "player", "giocatori"):
            if k in adb and adb[k]:
                badges.append(f"Players: {adb[k]}")
                break

        # buttons
        for k in ("buttons", "pulsanti"):
            if k in adb and adb[k]:
                badges.append(f"Buttons: {adb[k]}")
                break

        # controls
        for k in ("controls", "control", "controlli"):
            if k in adb and adb[k]:
                val = adb[k]
                if isinstance(val, (list, dict)):
                    badges.append("Controls: (see details)")
                else:
                    badges.append(f"Controls: {val}")
                break

        # orientation/rotation
        for k in ("rotation", "orientamento", "screen", "monitor"):
            if k in adb and adb[k]:
                badges.append(f"Orientation: {adb[k]}")
                break

        # working/status
        for k in ("status", "emulation", "driver_status"):
            if k in adb and adb[k]:
                badges.append(f"Status: {adb[k]}")
                break

    # "Use 4-way" hint (best effort)
    title_l = normalize_str(row.get("game", "")).lower()
    if any(x in title_l for x in ("pac-man", "puck man", "donkey kong", "dig dug", "galaga", "mappy", "frogger")):
        badges.append("Tip: use 4-way stick")

    return badges


# ----------------------------
# ADB (ArcadeItalia) on-demand integration
# ----------------------------
def adb_urls(rom: str):
    rom = (rom or "").strip().lower()
    page_https = f"https://adb.arcadeitalia.net/?mame={rom}"
    page_http = f"http://adb.arcadeitalia.net/?mame={rom}"

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
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (ArcadeGamePicker/1.5; +https://streamlit.app)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace").strip()
    data = json.loads(text)
    if isinstance(data, dict):
        return data
    return {"_data": data}


def fetch_adb_details(rom: str) -> dict:
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

    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def show_adb_block(rom: str):
    rom = (rom or "").strip().lower()
    if not rom:
        st.info("ADB details require a ROM short name; this entry has none.")
        return None

    urls = adb_urls(rom)
    st.markdown("**ADB links:**")
    st.write(f"- ADB page (HTTPS): {urls['page_https']}")
    st.write(f"- ADB page (HTTP fallback): {urls['page_http']}")

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        load_btn = st.button("📥 Load ADB details", key=f"adb_load_{rom}")
    with c2:
        force_refresh = st.button("♻️ Refresh", key=f"adb_refresh_{rom}")
    with c3:
        show_images = st.toggle("Show artwork/images (if provided)", value=True, key=f"adb_img_{rom}")

    if force_refresh and rom in st.session_state.adb_cache:
        del st.session_state.adb_cache[rom]

    if not load_btn and not force_refresh:
        # if already cached, show cached without re-click
        if rom in st.session_state.adb_cache and not st.session_state.adb_cache[rom].get("_error"):
            data = st.session_state.adb_cache[rom]
        else:
            return None
    else:
        with st.spinner("Fetching from ADB..."):
            data = fetch_adb_details(rom)

    if isinstance(data, dict) and data.get("_error"):
        st.error(data["_error"])
        if data.get("_detail"):
            st.caption(f"Details: {data['_detail']}")
        return data

    st.subheader("ADB Details (summary)")

    # Summary fields (best effort)
    for k in ("title", "description", "manufacturer", "year", "genre", "players", "buttons", "controls", "rotation", "status"):
        if k in data and data[k]:
            val = data[k]
            if isinstance(val, (dict, list)):
                st.write(f"**{k}:**")
                st.json(val)
            else:
                st.write(f"**{k}:** {val}")

    # If nothing matched, show raw response so you still get value
    if not any(k in data for k in ("title", "description", "manufacturer", "year", "genre", "players", "buttons", "controls")):
        st.caption("ADB returned data in an unexpected format; showing raw response.")
        st.json(data)

    if show_images:
        imgs = extract_image_urls(data)
        if imgs:
            st.subheader("Artwork / Images")
            for u in imgs[:8]:
                st.image(u, use_container_width=True)
        else:
            st.caption("No direct image URLs found in the ADB response for this title.")

    return data


# ----------------------------
# UI: details panel
# ----------------------------
def show_game_details(row: pd.Series):
    g = normalize_str(row.get("game", ""))
    y = int(row.get("year", 0))
    c = normalize_str(row.get("company", ""))
    genre = normalize_str(row.get("genre", ""))
    platform = normalize_str(row.get("platform", ""))
    rom = normalize_str(row.get("rom", "")).lower()

    st.markdown(f"## {g}")
    st.write(f"**Year:** {y}")
    if c:
        st.write(f"**Company:** {c}")
    if genre:
        st.write(f"**Genre:** {genre}")
    if platform:
        st.write(f"**Platform:** {platform}")
    if rom:
        st.write(f"**ROM (MAME short name):** `{rom}`")

    # Links
    st.markdown("### 🔗 Research links")
    for name, url in build_links(g).items():
        st.write(f"- {name}: {url}")

    st.markdown("---")
    st.markdown("### 🎮 Cabinet fit & controls")

    # If ADB already fetched for this ROM, use it; else none
    adb = st.session_state.adb_cache.get(rom) if rom else None
    badges = cabinet_fit_badges(row, adb if isinstance(adb, dict) else None)
    if badges:
        st.info(" • ".join(badges))

    st.write(
        "**Your cabinet profile:** 4-way stick + 8-way stick, 6 buttons/player, no spinner/trackball/lightgun/wheel, horizontal monitor (vertical OK)."
    )
    st.caption(
        "This app is in **STRICT** mode: it hides obvious non-compatible control types from discovery results."
    )

    st.markdown("---")
    st.markdown("### 📚 Arcade Database (ADB) details + artwork (on-demand)")
    adb_data = show_adb_block(rom)

    # If ADB now loaded, show updated badges
    if adb_data and isinstance(adb_data, dict) and not adb_data.get("_error"):
        st.markdown("---")
        st.markdown("### ✅ Updated fit hints (from ADB)")
        badges2 = cabinet_fit_badges(row, adb_data)
        if badges2:
            st.success(" • ".join(badges2))


# ----------------------------
# App start
# ----------------------------
init_state()

try:
    df = load_games_no_cache()
except FileNotFoundError:
    st.error(f"Could not find `{CSV_PATH}` in the repo root. Upload it to GitHub and redeploy.")
    st.stop()
except Exception as e:
    st.error("Failed to load CSV.")
    st.code(str(e))
    st.stop()

# ----------------------------
# Sidebar: Cabinet-first settings
# ----------------------------
st.sidebar.header("🎛️ Cabinet Mode")
st.sidebar.caption(APP_VERSION)

strict_mode = st.sidebar.toggle("STRICT: only show cabinet-playable games", value=True)
allow_vertical = st.sidebar.toggle("Allow vertical games", value=True)
max_buttons = st.sidebar.slider("Max buttons per player", min_value=1, max_value=6, value=6)

st.sidebar.markdown("---")
st.sidebar.header("Filters")
years = st.sidebar.slider("Year range", 1978, 2008, (1978, 2008))

# Optional additional filters
all_platforms = sorted(df["platform"].replace("", pd.NA).dropna().unique().tolist())
all_genres = sorted(df["genre"].replace("", pd.NA).dropna().unique().tolist())

platform_choice = st.sidebar.multiselect("Platform (optional)", all_platforms)
genre_choice = st.sidebar.multiselect("Genre (optional)", all_genres)

st.sidebar.markdown("---")
try:
    p = Path(CSV_PATH)
    st.sidebar.caption(f"CSV rows: {len(df):,}")
    st.sidebar.caption(f"CSV modified (server): {datetime.fromtimestamp(p.stat().st_mtime)}")
except Exception:
    pass

# ----------------------------
# Global search (always available, but respects strict mode by default)
# ----------------------------
st.markdown("## 🔎 Search")
search_name = st.text_input("Search by name (title) or ROM (e.g., pacman)", "")

# Base filter: year, optional platform/genre
base = df[(df["year"] >= years[0]) & (df["year"] <= years[1])].copy()

if platform_choice:
    base = base[base["platform"].isin(platform_choice)]
if genre_choice:
    base = base[base["genre"].isin(genre_choice)]

# STRICT cabinet filter
if strict_mode:
    base = base[base.apply(is_cabinet_compatible_strict, axis=1)]

# (Optional) vertical filter - we only have reliable orientation from ADB, so this is a soft toggle:
# we keep it enabled but won't remove by default due to missing orientation in CSV.
# If you later add "orientation" to CSV, we can enforce it here.
if not allow_vertical:
    # no reliable orientation in CSV, so we don't enforce. We keep the toggle for later.
    st.info("Vertical filtering requires orientation data. For now this toggle is reserved for a future dataset enhancement.")

base = base.sort_values(["year", "game"]).reset_index(drop=True)

# Search behavior: by title contains OR rom equals/contains
if search_name.strip():
    s = search_name.strip().lower()
    hits = base[
        base["_game_l"].str.contains(s, na=False)
        | base["rom"].astype(str).str.lower().str.contains(s, na=False)
    ].copy()
else:
    hits = base.copy()

st.write(f"Matches: **{len(hits):,}**")

st.divider()

# ----------------------------
# Two-panel layout: left discovery, right details
# ----------------------------
left, right = st.columns([1.1, 1.0], gap="large")

with left:
    st.markdown("## 🎲 Discover (cabinet-ready)")
    c1, c2, c3 = st.columns(3)
    with c1:
        pick_random = st.button("🎲 Random", use_container_width=True)
    with c2:
        pick_10 = st.button("🎯 10 Picks", use_container_width=True)
    with c3:
        clear_picks = st.button("🧹 Clear", use_container_width=True)

    if clear_picks:
        st.session_state.picked_rows = []
        st.session_state.selected_key = None
        st.rerun()

    if pick_random:
        if len(hits) == 0:
            st.warning("No games match your strict cabinet filters. Widen filters to discover more.")
        else:
            row = hits.sample(1).iloc[0]
            st.session_state.selected_key = game_key(row)
            st.rerun()

    if pick_10:
        if len(hits) == 0:
            st.warning("No games match your strict cabinet filters. Widen filters to discover more.")
        else:
            n = 10 if len(hits) >= 10 else len(hits)
            sample = hits.sample(n).copy()
            st.session_state.picked_rows = sample.to_dict("records")
            # auto-select first
            st.session_state.selected_key = game_key(pd.Series(st.session_state.picked_rows[0]))
            st.rerun()

    # Game of the Day (deterministic daily)
    st.markdown("### 📆 Game of the Day")
    now = datetime.now(TZ)
    seed = int(now.strftime("%Y")) * 1000 + int(now.strftime("%j"))
    if len(hits) > 0:
        gotd = hits.iloc[seed % len(hits)]
        if st.button("Open Game of the Day", use_container_width=True):
            st.session_state.selected_key = game_key(gotd)
            st.rerun()
        st.caption(f"Today: {gotd['game']} ({gotd['year']})")
    else:
        st.caption("No Game of the Day with current strict filters.")

    st.markdown("---")
    st.markdown("## 📜 Browse list")

    # Make a browse list (limit for UI)
    view = hits[["rom", "game", "year", "company", "genre", "platform"]].copy()
    st.dataframe(view, use_container_width=True, height=420)

    st.markdown("### Select a game")
    if len(view) == 0:
        st.info("No results to select. Adjust filters.")
    else:
        labels = (
            view["game"].astype(str)
            + " — "
            + view["year"].astype(str)
            + " — "
            + view["company"].astype(str)
        )
        selected_label = st.selectbox("Pick from results", labels, key="browse_select")
        idx = labels[labels == selected_label].index[0]
        selected_row = view.loc[idx]

        if st.button("➡️ Open selected", use_container_width=True):
            st.session_state.selected_key = game_key(selected_row)
            st.rerun()

    # Show 10-picks rail if present
    if st.session_state.picked_rows:
        st.markdown("---")
        st.markdown("## 🎯 Your 10 picks")
        pick_df = pd.DataFrame(st.session_state.picked_rows)
        pick_df = pick_df[["rom", "game", "year", "company", "genre", "platform"]]
        for i, r in pick_df.iterrows():
            label = f"{r['game']} ({int(r['year'])})"
            if st.button(label, key=f"pick_{i}", use_container_width=True):
                st.session_state.selected_key = game_key(r)
                st.rerun()

with right:
    st.markdown("## 🧾 Details")
    if not st.session_state.selected_key:
        st.info("Pick a game from the list or hit Random/10 Picks to see details.")
    else:
        # Find matching row in df/hits using key
        key = st.session_state.selected_key

        if key.startswith("rom:"):
            rom = key.split("rom:", 1)[1]
            match = df[df["rom"] == rom]
            if len(match) == 0:
                st.warning("Selected game not found in dataset.")
            else:
                show_game_details(match.iloc[0])
        else:
            # meta fallback: try match by exact game/year/company string
            # This is rare; most entries have ROM.
            try:
                _, meta = key.split("meta:", 1)
                title, year_str, company = meta.split("|", 2)
                year = int(year_str)
                match = df[(df["game"] == title) & (df["year"] == year) & (df["company"] == company)]
                if len(match) == 0:
                    st.warning("Selected game not found in dataset.")
                else:
                    show_game_details(match.iloc[0])
            except Exception:
                st.warning("Could not resolve selection key.")
