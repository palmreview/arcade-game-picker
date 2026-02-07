import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# ----------------------------
# Page config
# ----------------------------
st.set_page_config(page_title="Arcade Game Picker", layout="wide")

st.title("🕹️ Arcade Game Picker (1978–2008)")
st.caption(
    "Cabinet-first discovery: find games you can actually play at home, learn the history, and see artwork. "
    "CSV caching is disabled so data updates apply immediately. ADB details/artwork load on-demand (optionally auto-load). "
    "Status (Want to Play / Played) is stored globally in a server-side SQLite DB."
)

# ----------------------------
# Constants
# ----------------------------
TZ = ZoneInfo("America/New_York")
APP_VERSION = "1.8 • Strict Cabinet Mode • ADB robust parsing • HTTP-only ADB • Global status via SQLite • No caching"

CSV_PATH = "arcade_games_1978_2008_clean.csv"
DB_PATH = "game_state.db"

STATUS_WANT = "want_to_play"
STATUS_PLAYED = "played"

STATUS_LABELS = {
    None: "—",
    STATUS_WANT: "⏳ Want to Play",
    STATUS_PLAYED: "✅ Played",
}

# ----------------------------
# DB (global state across devices)
# ----------------------------
def get_db() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db() -> None:
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS game_status (
            rom TEXT PRIMARY KEY,
            status TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    conn.close()


def get_all_statuses() -> dict[str, str]:
    conn = get_db()
    cur = conn.execute("SELECT rom, status FROM game_status")
    rows = cur.fetchall()
    conn.close()
    out = {}
    for rom, status in rows:
        if rom:
            out[str(rom).strip().lower()] = status
    return out


def set_status(rom: str, status: str | None) -> None:
    rom = (rom or "").strip().lower()
    if not rom:
        return
    conn = get_db()
    if status is None:
        conn.execute("DELETE FROM game_status WHERE rom=?", (rom,))
    else:
        conn.execute(
            """
            INSERT INTO game_status (rom, status, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(rom) DO UPDATE SET
                status=excluded.status,
                updated_at=datetime('now')
            """,
            (rom, status),
        )
    conn.commit()
    conn.close()


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
        "Ports / Collections (search)": f"https://www.google.com/search?q={q}+arcade+collection+port",
    }


def game_key(row: pd.Series) -> str:
    rom = normalize_str(row.get("rom", "")).lower()
    if rom:
        return f"rom:{rom}"
    return f"meta:{normalize_str(row.get('game',''))}|{int(row.get('year',0))}|{normalize_str(row.get('company',''))}"


def init_state():
    if "picked_rows" not in st.session_state:
        st.session_state.picked_rows = []
    if "selected_key" not in st.session_state:
        st.session_state.selected_key = None
    if "adb_cache" not in st.session_state:
        st.session_state.adb_cache = {}
    if "status_cache" not in st.session_state:
        st.session_state.status_cache = {}
    if "status_cache_loaded" not in st.session_state:
        st.session_state.status_cache_loaded = False

    # ADB auto-load preferences
    if "adb_autoload_global" not in st.session_state:
        st.session_state.adb_autoload_global = False
    if "adb_autoload_by_rom" not in st.session_state:
        st.session_state.adb_autoload_by_rom = {}


# ----------------------------
# Cabinet profile + strict compatibility
# ----------------------------
CABINET_SUMMARY = (
    "Your cabinet: 4-way stick + 8-way stick, 6 buttons/player, NO spinner/trackball/lightgun/wheel, "
    "horizontal monitor (vertical OK)."
)

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

BLOCKED_GENRE_CONTAINS = [
    "driving",
    "racing",
    "pinball",
    "redemption",
]

BLOCKED_TITLE_HINTS = [
    "lightgun",
    "light gun",
    "trackball",
    "spinner",
    "steering",
    "wheel",
    "pedal",
    "paddle",
]


def is_cabinet_compatible_strict(row: pd.Series) -> bool:
    genre = normalize_str(row.get("genre", "")).strip().lower()
    title = normalize_str(row.get("game", "")).strip().lower()
    platform = normalize_str(row.get("platform", "")).strip().lower()

    if not genre and not title:
        return False

    if genre in BLOCKED_GENRE_EXACT:
        return False

    for frag in BLOCKED_GENRE_CONTAINS:
        if frag in genre:
            return False

    if any(x in platform for x in ("gambling", "casino", "slot", "quiz")):
        return False

    for hint in BLOCKED_TITLE_HINTS:
        if hint in title:
            return False

    return True


# ----------------------------
# ADB (ArcadeItalia) integration (HTTP-only) + robust parsing
# ----------------------------
def adb_urls(rom: str):
    rom = (rom or "").strip().lower()
    page_http = f"http://adb.arcadeitalia.net/?mame={rom}"
    params = {"ajax": "query_mame", "lang": "en", "game_name": rom}
    scraper_http = "http://adb.arcadeitalia.net/service_scraper.php?" + urlencode(params)
    return {"page_http": page_http, "scraper_http": scraper_http}


def fetch_json_url(url: str, timeout_sec: int = 12) -> dict:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (ArcadeGamePicker/1.8; +https://streamlit.app)",
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
    try:
        data = fetch_json_url(urls["scraper_http"], timeout_sec=12)
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
                if s.startswith("https://adb.arcadeitalia.net/"):
                    s = "http://adb.arcadeitalia.net/" + s.split("https://adb.arcadeitalia.net/", 1)[1]
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


def adb_autoload_effective(rom: str) -> bool:
    rom = (rom or "").strip().lower()
    if not rom:
        return False
    if rom in st.session_state.adb_autoload_by_rom:
        return bool(st.session_state.adb_autoload_by_rom[rom])
    return bool(st.session_state.adb_autoload_global)


def _walk_kv(obj):
    def rec(x, path):
        if isinstance(x, dict):
            for k, v in x.items():
                yield (path, k, v)
                yield from rec(v, path + [str(k)])
        elif isinstance(x, list):
            for i, v in enumerate(x):
                yield from rec(v, path + [f"[{i}]"])
    yield from rec(obj, [])


def _find_first_value(obj, key_candidates):
    cands = {c.lower() for c in key_candidates}
    for path, k, v in _walk_kv(obj):
        if str(k).strip().lower() in cands and v not in (None, "", [], {}):
            path_str = ".".join(path + [str(k)])
            return v, path_str, k
    return None, None, None


def _coerce_text(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v).strip()


def parse_adb_summary(data: dict) -> tuple[dict, dict]:
    candidates = [data]
    for wrap_key in ("result", "data", "game", "mame", "response"):
        if isinstance(data.get(wrap_key), dict):
            candidates.append(data[wrap_key])
        elif isinstance(data.get(wrap_key), list) and data[wrap_key]:
            if isinstance(data[wrap_key][0], dict):
                candidates.append(data[wrap_key][0])

    field_map = {
        "title": ["title", "name", "game", "game_name", "nome", "titolo"],
        "description": ["description", "desc", "note", "descrizione", "storia", "history"],
        "manufacturer": ["manufacturer", "company", "maker", "produttore", "manufacturer_name"],
        "year": ["year", "release_year", "anno", "data", "date"],
        "genre": ["genre", "category", "genere", "tipo"],
        "players": ["players", "player", "giocatori", "num_players"],
        "buttons": ["buttons", "button", "pulsanti", "num_buttons"],
        "controls": ["controls", "control", "input", "controlli", "controllo", "joystick"],
        "rotation": ["rotation", "screen", "orientation", "orientamento", "monitor", "display"],
        "status": ["status", "working", "emulation", "emulation_status", "stato"],
    }

    summary = {}
    paths = {}

    for norm_key, key_cands in field_map.items():
        val = None
        path_used = None
        key_used = None
        for obj in candidates:
            val, path_used, key_used = _find_first_value(obj, key_cands)
            if val is not None:
                break
        if val is not None:
            summary[norm_key] = _coerce_text(val)
            paths[norm_key] = {"path": path_used, "key": str(key_used)}

    if "year" in summary:
        m = re.search(r"(19\d{2}|20\d{2})", summary["year"])
        if m:
            summary["year"] = m.group(1)

    return summary, {"extracted_paths": paths, "wrap_candidates": [type(x).__name__ for x in candidates]}



def show_adb_block(rom: str):
    rom = (rom or "").strip().lower()
    if not rom:
        st.info("ADB details require a ROM short name; this entry has none.")
        return None

    urls = adb_urls(rom)

    with st.expander("ADB details + artwork", expanded=False):
        current_auto = adb_autoload_effective(rom)
        auto_val = st.toggle(
            "Auto-load ADB for this game",
            value=current_auto,
            key=f"adb_autoload_{rom}",
            help="If enabled, ADB details will fetch automatically when you open this game (unless already cached).",
        )
        st.session_state.adb_autoload_by_rom[rom] = bool(auto_val)

        st.markdown("**ADB links (HTTP-only):**")
        st.write(f"- ADB page: {urls['page_http']}")
        st.write(f"- Scraper (HTTP): {urls['scraper_http']}")

        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            load_btn = st.button("📥 Load ADB details", key=f"adb_load_{rom}")
        with c2:
            refresh_btn = st.button("♻️ Refresh", key=f"adb_refresh_{rom}")
        with c3:
            show_images = st.toggle("Show artwork/images (if provided)", value=True, key=f"adb_img_{rom}")

        if refresh_btn and rom in st.session_state.adb_cache:
            del st.session_state.adb_cache[rom]

        should_autoload_now = bool(auto_val) and (
            rom not in st.session_state.adb_cache
            or bool(st.session_state.adb_cache.get(rom, {}).get("_error"))
        )

        if (rom not in st.session_state.adb_cache) and (not load_btn) and (not refresh_btn) and (not should_autoload_now):
            st.info("ADB is not loaded yet. Click **📥 Load ADB details** (or enable **Auto-load** above).")
            return None

        if load_btn or refresh_btn or should_autoload_now:
            with st.spinner("Fetching from ADB..."):
                data = fetch_adb_details(rom)
        else:
            data = st.session_state.adb_cache.get(rom)

        if not isinstance(data, dict):
            st.warning("ADB returned an unexpected response format.")
            st.json(data)
            return data

        if data.get("_error"):
            st.error(data["_error"])
            if data.get("_detail"):
                st.caption(f"Details: {data['_detail']}")
            if data.get("_fallback_page"):
                st.write(f"Try opening the ADB page directly: {data['_fallback_page']}")
            return data

        summary, dbg = parse_adb_summary(data)

        if summary:
            st.subheader("ADB Details")
            order = ["title", "manufacturer", "year", "genre", "players", "buttons", "controls", "rotation", "status", "description"]
            for k in order:
                if k in summary and summary[k]:
                    label = k.replace("_", " ").title()
                    st.write(f"**{label}:** {summary[k]}")
        else:
            st.warning("ADB returned data but no recognizable fields were found.")

        # ---- No nested expanders! Use tabs instead. ----
        tab_art, tab_debug, tab_raw = st.tabs(["🖼️ Artwork", "🧩 Parse debug", "🧾 Raw JSON"])

        with tab_art:
            if not show_images:
                st.caption("Artwork display is turned off.")
            else:
                imgs = extract_image_urls(data)

                # If ADB returns image links without obvious extensions, keep a few additional candidates
                # (ADB commonly serves media under /media/ and sometimes uses query strings).
                if not imgs:
                    extra = []
                    for _, k, v in _walk_kv(data):
                        if isinstance(v, str):
                            s = v.strip()
                            if "adb.arcadeitalia.net" in s and ("/media/" in s or "media" in s.lower()):
                                if s.startswith("https://adb.arcadeitalia.net/"):
                                    s = "http://adb.arcadeitalia.net/" + s.split("https://adb.arcadeitalia.net/", 1)[1]
                                if s.startswith("//adb.arcadeitalia.net/"):
                                    s = "http:" + s
                                if s.startswith("http://adb.arcadeitalia.net/") or s.startswith("https://adb.arcadeitalia.net/"):
                                    extra.append(s)
                    # de-dupe while preserving order
                    seen = set()
                    imgs = []
                    for u in extra:
                        if u not in seen:
                            seen.add(u)
                            imgs.append(u)

                if imgs:
                    st.caption(f"Found {len(imgs)} image URL(s). Showing up to 12.")
                    for u in imgs[:12]:
                        try:
                            st.image(u, use_container_width=True)
                        except Exception as e:
                            st.warning(f"Could not render image: {u}")
                            st.caption(str(e))
                else:
                    st.caption("No image URLs found in the ADB response for this title.")

        with tab_debug:
            st.json(dbg)

        with tab_raw:
            st.json(data)

        return data


# ----------------------------
# Status UI + caching
# ----------------------------
def load_status_cache_once():
    if not st.session_state.status_cache_loaded:
        st.session_state.status_cache = get_all_statuses()
        st.session_state.status_cache_loaded = True


def status_for_rom(rom: str) -> str | None:
    rom = (rom or "").strip().lower()
    if not rom:
        return None
    return st.session_state.status_cache.get(rom)


def update_status(rom: str, new_status: str | None):
    rom = (rom or "").strip().lower()
    if not rom:
        return
    set_status(rom, new_status)
    if new_status is None:
        st.session_state.status_cache.pop(rom, None)
    else:
        st.session_state.status_cache[rom] = new_status


# ----------------------------
# Details panel
# ----------------------------
def show_game_details(row: pd.Series):
    g = normalize_str(row.get("game", ""))
    y = int(row.get("year", 0))
    c = normalize_str(row.get("company", ""))
    genre = normalize_str(row.get("genre", ""))
    platform = normalize_str(row.get("platform", ""))
    rom = normalize_str(row.get("rom", "")).lower()

    cur_status = status_for_rom(rom)
    st.markdown(f"## {g}")
    st.write(f"**Status:** {STATUS_LABELS.get(cur_status, '—')}")
    st.caption(CABINET_SUMMARY)

    s1, s2, s3 = st.columns([1, 1, 1])
    with s1:
        if st.button("⏳ Want to Play", use_container_width=True, key=f"st_want_{rom}"):
            update_status(rom, STATUS_WANT)
            st.rerun()
    with s2:
        if st.button("✅ Played", use_container_width=True, key=f"st_played_{rom}"):
            update_status(rom, STATUS_PLAYED)
            st.rerun()
    with s3:
        if st.button("🧽 Clear", use_container_width=True, key=f"st_clear_{rom}"):
            update_status(rom, None)
            st.rerun()

    st.write(f"**Year:** {y}")
    if c:
        st.write(f"**Company:** {c}")
    if genre:
        st.write(f"**Genre:** {genre}")
    if platform:
        st.write(f"**Platform:** {platform}")
    if rom:
        st.write(f"**ROM (MAME short name):** `{rom}`")

    st.markdown("### 📚 Arcade Database (ADB) (HTTP-only, on-demand / optional auto-load)")
    show_adb_block(rom)

    # ----------------------------
    # Research links (rolled-up with dropdown)
    # ----------------------------
    st.markdown("---")
    st.markdown("### 🔎 Research")

    links = build_links(g)
    # A small "rolled-up" UI: pick one link at a time
    link_names = ["— Select a research link —"] + list(links.keys())
    choice = st.selectbox("Research links", link_names, key=f"research_dd_{rom or g}")

    if choice and choice != "— Select a research link —":
        url = links.get(choice, "")
        if url:
            # Streamlit link_button is nicer when available; fall back to markdown if not.
            if hasattr(st, "link_button"):
                st.link_button(f"Open: {choice}", url, use_container_width=True)
            else:
                st.markdown(f"[Open: {choice}]({url})")
        else:
            st.info("No URL found for this selection.")


# ----------------------------
# Boot app
# ----------------------------
init_state()
init_db()

try:
    df = load_games_no_cache()
except FileNotFoundError:
    st.error(f"Could not find `{CSV_PATH}` in the repo root. Upload it to GitHub and redeploy.")
    st.stop()
except Exception as e:
    st.error("Failed to load CSV.")
    st.code(str(e))
    st.stop()

load_status_cache_once()

# ----------------------------
# Sidebar: Cabinet mode + status filtering
# ----------------------------
st.sidebar.header("🎛️ Cabinet Mode")
st.sidebar.caption(APP_VERSION)

strict_mode = st.sidebar.toggle("STRICT: only show cabinet-playable games", value=True)

st.sidebar.markdown("---")
st.sidebar.header("📚 ADB (ArcadeItalia)")
st.sidebar.toggle(
    "Auto-load ADB details when opening a game (global default)",
    value=st.session_state.adb_autoload_global,
    key="adb_autoload_global",
    help="Sets the default. You can override per-game inside the ADB expander.",
)

st.sidebar.markdown("---")
st.sidebar.header("✅ Status filters")
hide_played = st.sidebar.toggle("Hide ✅ Played", value=True)
only_want = st.sidebar.toggle("Show only ⏳ Want to Play", value=False)

st.sidebar.markdown("---")
st.sidebar.header("Filters")
years = st.sidebar.slider("Year range", 1978, 2008, (1978, 2008))
platforms = sorted(df["platform"].replace("", pd.NA).dropna().unique().tolist())
genres = sorted(df["genre"].replace("", pd.NA).dropna().unique().tolist())
platform_choice = st.sidebar.multiselect("Platform (optional)", platforms)
genre_choice = st.sidebar.multiselect("Genre (optional)", genres)

st.sidebar.markdown("---")
try:
    p = Path(CSV_PATH)
    st.sidebar.caption(f"CSV rows: {len(df):,}")
    st.sidebar.caption(f"CSV modified (server): {datetime.fromtimestamp(p.stat().st_mtime)}")
except Exception:
    pass

# ----------------------------
# Build filtered view
# ----------------------------
base = df[(df["year"] >= years[0]) & (df["year"] <= years[1])].copy()
if platform_choice:
    base = base[base["platform"].isin(platform_choice)]
if genre_choice:
    base = base[base["genre"].isin(genre_choice)]
if strict_mode:
    base = base[base.apply(is_cabinet_compatible_strict, axis=1)].copy()


def keep_by_status(row: pd.Series) -> bool:
    rom = normalize_str(row.get("rom", "")).lower()
    s = status_for_rom(rom)
    if only_want:
        return s == STATUS_WANT
    if hide_played and s == STATUS_PLAYED:
        return False
    return True


base = base[base.apply(keep_by_status, axis=1)].copy()
base = base.sort_values(["year", "game"]).reset_index(drop=True)

# ----------------------------
# Search
# ----------------------------
st.markdown("## 🔎 Search")
search_name = st.text_input("Search by name or ROM (e.g., pacman, sf2, metal slug)", "")

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
# Two-panel layout
# ----------------------------
left, right = st.columns([1.15, 1.0], gap="large")

with left:
    st.markdown("## 🎲 Discover (cabinet-ready)")

    c1, c2, c3 = st.columns(3)
    with c1:
        pick_random = st.button("🎲 Random", use_container_width=True)
    with c2:
        pick_10 = st.button("🎯 10 Picks", use_container_width=True)
    with c3:
        clear_sel = st.button("🧹 Clear selection", use_container_width=True)

    if clear_sel:
        st.session_state.picked_rows = []
        st.session_state.selected_key = None
        st.rerun()

    if pick_random:
        if len(hits) == 0:
            st.warning("No games match your current strict cabinet + status filters. Widen filters.")
        else:
            row = hits.sample(1).iloc[0]
            st.session_state.selected_key = game_key(row)
            st.rerun()

    if pick_10:
        if len(hits) == 0:
            st.warning("No games match your current strict cabinet + status filters. Widen filters.")
        else:
            n = min(10, len(hits))
            sample = hits.sample(n).copy()
            st.session_state.picked_rows = sample.to_dict("records")
            st.session_state.selected_key = game_key(pd.Series(st.session_state.picked_rows[0]))
            st.rerun()

    st.markdown("### 📆 Game of the Day")
    now = datetime.now(TZ)
    seed = int(now.strftime("%Y")) * 1000 + int(now.strftime("%j"))
    if len(hits) > 0:
        gotd = hits.iloc[seed % len(hits)]
        st.caption(f"Today: {gotd['game']} ({gotd['year']})")
        if st.button("Open Game of the Day", use_container_width=True):
            st.session_state.selected_key = game_key(gotd)
            st.rerun()
    else:
        st.caption("No Game of the Day with current filters.")

    st.markdown("---")
    st.markdown("## 📜 Browse list")

    view = hits[["rom", "game", "year", "company", "genre", "platform"]].copy()
    view["status"] = view["rom"].apply(lambda r: STATUS_LABELS.get(status_for_rom(str(r).lower()), "—"))
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
            + " — "
            + view["status"].astype(str)
        )
        selected_label = st.selectbox("Pick from results", labels, key="browse_select")
        idx = labels[labels == selected_label].index[0]
        selected_row = view.loc[idx]

        if st.button("➡️ Open selected", use_container_width=True):
            st.session_state.selected_key = game_key(selected_row)
            st.rerun()

    if st.session_state.picked_rows:
        st.markdown("---")
        st.markdown("## 🎯 Your 10 picks")
        pick_df = pd.DataFrame(st.session_state.picked_rows)
        pick_df = pick_df[["rom", "game", "year", "company", "genre", "platform"]].copy()
        pick_df["status"] = pick_df["rom"].apply(lambda r: STATUS_LABELS.get(status_for_rom(str(r).lower()), "—"))

        for i, r in pick_df.iterrows():
            label = f"{r['game']} ({int(r['year'])}) — {r['status']}"
            if st.button(label, key=f"pick_{i}", use_container_width=True):
                st.session_state.selected_key = game_key(r)
                st.rerun()

with right:
    st.markdown("## 🧾 Details")
    if not st.session_state.selected_key:
        st.info("Pick a game from the list or hit Random/10 Picks to see details.")
    else:
        key = st.session_state.selected_key
        if key.startswith("rom:"):
            rom = key.split("rom:", 1)[1]
            match = df[df["rom"] == rom]
            if len(match) == 0:
                st.warning("Selected game not found in dataset.")
            else:
                show_game_details(match.iloc[0])
        else:
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
