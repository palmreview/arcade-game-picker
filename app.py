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

# ----------------------------
# Constants
# ----------------------------
TZ = ZoneInfo("America/New_York")

APP_VERSION = (
    "1.13 • Restored baseline + ADB + Research rollups • Added: Marquees (R2), Want export, "
    "Not playable, Don't have ROM • SQLite status (may reset on Streamlit Cloud restart)"
)

CSV_PATH = "arcade_games_1978_2008_clean.csv"
DB_PATH = "game_state.db"

# --- Cloudflare R2 Public Development URL (r2.dev)
# Your objects are expected at:
#   {R2_PUBLIC_ROOT}/marquees/<rom>.png
#   {R2_PUBLIC_ROOT}/marquees/default.png
R2_PUBLIC_ROOT = "https://pub-04cb80aef9834a5d908ddf7538b7fffa.r2.dev"
MARQUEE_PATH_PREFIX = "marquees"

STATUS_WANT = "want_to_play"
STATUS_PLAYED = "played"
STATUS_NO_ROM = "dont_have_rom"
STATUS_BLOCKED = "not_playable"

STATUS_LABELS = {
    None: "—",
    STATUS_WANT: "⏳ Want to Play",
    STATUS_PLAYED: "✅ Played",
    STATUS_NO_ROM: "🧩 Don't have ROM",
    STATUS_BLOCKED: "🚫 Not playable",
}

# ----------------------------
# Header
# ----------------------------
st.title("🕹️ Arcade Game Picker (1978–2008)")
st.caption(
    "Cabinet-first discovery: find games you can actually play at home, learn the history, and see artwork. "
    "ADB details/artwork load on-demand. Marquees load from Cloudflare R2 (r2.dev). "
    "Status is stored in SQLite in this version (may reset on Streamlit Cloud restarts)."
)

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


def normalize_str(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()


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
# DB (global state across devices) - SQLite
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
    out: dict[str, str] = {}
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
# Session state
# ----------------------------
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
    if "marquee_exists_cache" not in st.session_state:
        st.session_state.marquee_exists_cache = {}


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
# Dataset
# ----------------------------
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


# ----------------------------
# Links / keys
# ----------------------------
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
# Marquees (Cloudflare R2)
# ---------------------
