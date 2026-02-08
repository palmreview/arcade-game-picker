import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
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
    "CSV caching is disabled so data updates apply immediately. ADB details/artwork load on-demand. "
    "Status (Want to Play / Played) is stored globally in a server-side SQLite DB."
)

# ----------------------------
# Constants
# ----------------------------
TZ = ZoneInfo("America/New_York")
APP_VERSION = "1.7.x • Baseline v1.7 + Marquees (R2) + Status: Want/Played/Don’t have ROM/Not playable • ADB on-demand • Global status via SQLite • No CSV caching"

CSV_PATH = "arcade_games_1978_2008_clean.csv"
DB_PATH = "game_state.db"

# --- Cloudflare R2 Public URL (r2.dev)
# Files expected at bucket root:
#   {R2_PUBLIC_ROOT}/<rom>.png
#   {R2_PUBLIC_ROOT}/default.png
R2_PUBLIC_ROOT = "https://pub-04cb80aef9834a5d908ddf7538b7fffa.r2.dev"

STATUS_WANT = "want_to_play"
STATUS_PLAYED = "played"
STATUS_NO_ROM = "dont_have_rom"
STATUS_NOT_PLAYABLE = "not_playable"

STATUS_LABELS = {
    None: "—",
    STATUS_WANT: "⏳ Want to Play",
    STATUS_PLAYED: "✅ Played",
    STATUS_NO_ROM: "🧩 Don’t have ROM",
    STATUS_NOT_PLAYABLE: "🚫 Not playable",
}
# ----------------------------
# DB (global state across devices)
# ----------------------------
def get_db() -> sqlite3.Connection:
    # check_same_thread False is fine for Streamlit single-process usage
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
    """
    Returns mapping: rom -> status
    """
    conn = get_db()
    cur = conn.execute("SELECT rom, status FROM game_status")
    rows = cur.fetchall()
    conn.close()
    out = {}
    for rom, status in rows:
        if rom:
            out[str(rom).strip().lower()] = status
    return out

def get_status(rom: str) -> str | None:
    rom = (rom or "").strip().lower()
    if not rom:
        return None
    conn = get_db()
    cur = conn.execute("SELECT status FROM game_status WHERE rom=?", (rom,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

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
    if "show_marquees" not in st.session_state:
        st.session_state.show_marquees = True
    if "marquee_cache" not in st.session_state:
        # rom -> bool (exists)
        st.session_state.marquee_cache = {}

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
            "User-Agent": "Mozilla/5.0 (ArcadeGamePicker/1.7; +https://streamlit.app)",
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
        refresh_btn = st.button("♻️ Refresh", key=f"adb_refresh_{rom}")
    with c3:
        show_images = st.toggle("Show artwork/images (if provided)", value=True, key=f"adb_img_{rom}")

    if refresh_btn and rom in st.session_state.adb_cache:
        del st.session_state.adb_cache[rom]

    if not load_btn and not refresh_btn:
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
    for k in ("title", "description", "manufacturer", "year", "genre", "players", "buttons", "controls", "rotation", "status"):
        if k in data and data[k]:
            val = data[k]
            if isinstance(val, (dict, list)):
                st.write(f"**{k}:**")
                st.json(val)
            else:
                st.write(f"**{k}:** {val}")

    if show_images:
        imgs = extract_image_urls(data)
        if imgs:
            st.subheader("Artwork / Images")
            for u in imgs[:10]:
                _st_image(u)
        else:
            st.caption("No direct image URLs found in the ADB response for this title.")

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
    # Update in-memory cache immediately
    if new_status is None:
        st.session_state.status_cache.pop(rom, None)
    else:
        st.session_state.status_cache[rom] = new_status


# ----------------------------
# Export: Want to Play (.txt)
# ----------------------------
def build_want_to_play_txt(df: pd.DataFrame) -> str:
    want_roms = {rom for rom, status in st.session_state.status_cache.items() if status == STATUS_WANT}
    if not want_roms:
        return "No games marked as Want to Play."

    subset = df[df["rom"].isin(want_roms)].copy()
    subset = subset.sort_values(["year", "game"])

    lines: list[str] = []
    for _, row in subset.iterrows():
        game = row.get("game", "")
        year = row.get("year", "")
        company = row.get("company", "")
        genre = row.get("genre", "")
        rom = row.get("rom", "")
        lines.append(f"{game} ({year}) — {company} — {genre} — ROM: {rom}")

    return "\n".join(lines)

# ----------------------------
# Details panel
# ----------------------------

# ----------------------------
# Marquees (Cloudflare R2)
# ----------------------------
def _st_image(img, *, caption: str | None = None):
    """Render images compatibly across Streamlit versions."""
    try:
        st.image(img, caption=caption, use_container_width=True)
    except TypeError:
        st.image(img, caption=caption, use_column_width=True)


def _fetch_image_bytes(url: str, timeout_sec: int = 8) -> bytes | None:
    """Fetch an image as bytes (more reliable than hotlinking)."""
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (ArcadeGamePicker)",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        with urlopen(req, timeout=timeout_sec) as resp:
            return resp.read()
    except (HTTPError, URLError):
        return None
    except Exception:
        return None


def _marquee_url(rom: str) -> str:
    rom = (rom or "").strip().lower()
    if not rom:
        return f"{R2_PUBLIC_ROOT}/default.png"
    return f"{R2_PUBLIC_ROOT}/{rom}.png"


def _default_marquee_url() -> str:
    return f"{R2_PUBLIC_ROOT}/default.png"


def show_marquee(rom: str):
    """Show the marquee above details. Falls back to default.png."""
    if not getattr(st.session_state, "show_marquees", True):
        return

    rom = (rom or "").strip().lower()
    cache: dict = getattr(st.session_state, "marquee_cache", {})

    # Try ROM-specific first
    if rom:
        if rom not in cache:
            cache[rom] = _fetch_image_bytes(_marquee_url(rom), timeout_sec=6) is not None
            st.session_state.marquee_cache = cache

        if cache.get(rom):
            img = _fetch_image_bytes(_marquee_url(rom), timeout_sec=10)
            if img:
                _st_image(img)
                return

    # Default fallback
    default_bytes = _fetch_image_bytes(_default_marquee_url(), timeout_sec=10)
    if default_bytes:
        _st_image(default_bytes)
    else:
        st.caption("Marquee unavailable (could not load default.png).")
        st.write(_default_marquee_url())


def show_game_details(row: pd.Series):
    g = normalize_str(row.get("game", ""))
    y = int(row.get("year", 0))
    c = normalize_str(row.get("company", ""))
    genre = normalize_str(row.get("genre", ""))
    platform = normalize_str(row.get("platform", ""))
    rom = normalize_str(row.get("rom", "")).lower()

    # Marquee
    show_marquee(rom)

    # Status controls
    cur_status = status_for_rom(rom)
    st.markdown(f"## {g}")
    st.write(f"**Status:** {STATUS_LABELS.get(cur_status, '—')}")
    st.caption(CABINET_SUMMARY)

    if cur_status == STATUS_NOT_PLAYABLE:
        st.warning("This game is marked 🚫 Not playable and is hidden from discovery by default.")
    elif cur_status == STATUS_NO_ROM:
        st.info("This game is marked 🧩 Don’t have ROM and is hidden from discovery by default.")

    s1, s2, s3, s4, s5 = st.columns([1, 1, 1, 1, 1])
    with s1:
        if st.button("⏳ Want to Play", use_container_width=True, key=f"st_want_{rom}"):
            update_status(rom, STATUS_WANT)
            st.rerun()
    with s2:
        if st.button("✅ Played", use_container_width=True, key=f"st_played_{rom}"):
            update_status(rom, STATUS_PLAYED)
            st.rerun()
    with s3:
        if st.button("🧩 Don’t have ROM", use_container_width=True, key=f"st_norom_{rom}"):
            update_status(rom, STATUS_NO_ROM)
            st.rerun()
    with s4:
        if st.button("🚫 Not playable", use_container_width=True, key=f"st_noplay_{rom}"):
            update_status(rom, STATUS_NOT_PLAYABLE)
            st.rerun()
    with s5:
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

    with st.expander("📚 Arcade Database (ADB) details + artwork (on-demand)", expanded=False):
        show_adb_block(rom)

    with st.expander("🔗 Other research links", expanded=False):
        for name, url in build_links(g).items():
            st.write(f"- {name}: {url}")
# ----------------------------
# Boot app
# ----------------------------
init_state()
init_db()

# Load dataset (no caching)
try:
    df = load_games_no_cache()
except FileNotFoundError:
    st.error(f"Could not find `{CSV_PATH}` in the repo root. Upload it to GitHub and redeploy.")
    st.stop()
except Exception as e:
    st.error("Failed to load CSV.")
    st.code(str(e))
    st.stop()

# Load status cache once per session (global data)
load_status_cache_once()

# ----------------------------
# Sidebar: Cabinet mode + status filtering
# ----------------------------
st.sidebar.header("🎛️ Cabinet Mode")
st.sidebar.caption(APP_VERSION)

strict_mode = st.sidebar.toggle("STRICT: only show cabinet-playable games", value=True)
st.session_state.show_marquees = st.sidebar.toggle("Show marquees", value=st.session_state.get("show_marquees", True))

st.sidebar.markdown("---")
st.sidebar.header("✅ Status filters")

hide_played = st.sidebar.toggle("Hide ✅ Played", value=True)
only_want = st.sidebar.toggle("Show only ⏳ Want to Play", value=False)

# Hide these by default (they clutter discovery)
show_no_rom = st.sidebar.toggle("Show 🧩 Don’t have ROM", value=False)
show_not_playable = st.sidebar.toggle("Show 🚫 Not playable", value=False)

st.sidebar.markdown("---")
want_count = sum(1 for s in st.session_state.status_cache.values() if s == STATUS_WANT)
st.sidebar.download_button(
    label=f"📤 Export Want to Play ({want_count})",
    data=build_want_to_play_txt(df),
    file_name="arcade_want_to_play.txt",
    mime="text/plain",
    use_container_width=True,
)

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
    base = base[base.apply(is_cabinet_compatible_strict, axis=1)]

# Apply status filters
def keep_by_status(row: pd.Series) -> bool:
    rom = normalize_str(row.get("rom", "")).lower()
    s = status_for_rom(rom)

    # Hide these by default unless explicitly included
    if (not show_no_rom) and s == STATUS_NO_ROM:
        return False
    if (not show_not_playable) and s == STATUS_NOT_PLAYABLE:
        return False

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

    # Add status column for display
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
            # meta fallback (rare)
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
