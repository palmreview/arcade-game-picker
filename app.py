import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

# ============================
# Arcade Game Picker
# v1.8-ui • Arcade Retro aesthetic + Game Cards + Cleaner Details
# ============================

st.set_page_config(page_title="Arcade Game Picker", layout="wide")

# ----------------------------
# Custom CSS — Arcade Retro aesthetic
# ----------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&family=Exo+2:wght@300;400;600&display=swap');

:root {
  --arcade-bg:       #0a0a12;
  --arcade-surface:  #12121e;
  --arcade-panel:    #1a1a2e;
  --arcade-border:   #2a2a4a;
  --arcade-yellow:   #f5c518;
  --arcade-cyan:     #00e5ff;
  --arcade-magenta:  #ff2d78;
  --arcade-green:    #39ff14;
  --arcade-dim:      #6b6b8a;
  --arcade-text:     #e8e8f0;
  --arcade-subtext:  #9898b8;
}

html, body, [data-testid="stAppViewContainer"] {
  background-color: var(--arcade-bg) !important;
  color: var(--arcade-text) !important;
  font-family: 'Exo 2', sans-serif !important;
}
[data-testid="stSidebar"] {
  background-color: var(--arcade-surface) !important;
  border-right: 1px solid var(--arcade-border);
}

h1 { font-family: 'Orbitron', monospace !important; color: var(--arcade-yellow) !important;
     text-shadow: 0 0 20px rgba(245,197,24,0.4); letter-spacing: 2px; }
h2 { font-family: 'Orbitron', monospace !important; color: var(--arcade-cyan) !important;
     text-shadow: 0 0 12px rgba(0,229,255,0.3); font-size: 1.1rem !important; }
h3 { font-family: 'Orbitron', monospace !important; color: var(--arcade-text) !important; font-size: 0.95rem !important; }

/* ── Game card ── */
.game-card {
  background: var(--arcade-panel);
  border: 1px solid var(--arcade-border);
  border-left: 3px solid var(--arcade-cyan);
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 7px;
  font-family: 'Exo 2', sans-serif;
}
.game-card-title {
  font-family: 'Orbitron', monospace;
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--arcade-text);
  letter-spacing: 0.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.game-card-meta {
  font-family: 'Share Tech Mono', monospace;
  font-size: 0.65rem;
  color: var(--arcade-subtext);
  margin-top: 3px;
}
.game-card-meta span { margin-right: 10px; }

/* ── Status badges ── */
.badge { display:inline-block; padding:1px 7px; border-radius:3px;
  font-family:'Share Tech Mono',monospace; font-size:0.6rem; font-weight:700; letter-spacing:0.5px; }
.badge-want     { background:rgba(245,197,24,0.15); color:var(--arcade-yellow); border:1px solid rgba(245,197,24,0.4); }
.badge-played   { background:rgba(57,255,20,0.12);  color:var(--arcade-green);  border:1px solid rgba(57,255,20,0.4); }
.badge-norom    { background:rgba(0,229,255,0.10);  color:var(--arcade-cyan);   border:1px solid rgba(0,229,255,0.3); }
.badge-noplay   { background:rgba(255,45,120,0.12); color:var(--arcade-magenta);border:1px solid rgba(255,45,120,0.35);}
.badge-none     { background:rgba(107,107,138,0.15);color:var(--arcade-dim);    border:1px solid rgba(107,107,138,0.3);}

/* ── Detail panel ── */
.detail-title {
  font-family: 'Orbitron', monospace;
  font-size: 1.1rem;
  font-weight: 900;
  color: var(--arcade-yellow);
  text-shadow: 0 0 16px rgba(245,197,24,0.3);
  line-height: 1.3;
  margin-bottom: 4px;
}
.detail-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 8px;
  margin: 10px 0 14px 0;
  padding: 10px 12px;
  background: var(--arcade-panel);
  border: 1px solid var(--arcade-border);
  border-radius: 5px;
}
.detail-meta-item strong {
  color: var(--arcade-dim);
  text-transform: uppercase;
  font-size: 0.58rem;
  letter-spacing: 0.8px;
  font-family: 'Share Tech Mono', monospace;
  display: block;
  margin-bottom: 2px;
}
.detail-meta-item span {
  font-family: 'Share Tech Mono', monospace;
  font-size: 0.72rem;
  color: var(--arcade-text);
}
.detail-rom {
  font-family: 'Share Tech Mono', monospace;
  font-size: 0.72rem;
  color: var(--arcade-magenta);
  background: rgba(255,45,120,0.08);
  border: 1px solid rgba(255,45,120,0.2);
  padding: 2px 8px;
  border-radius: 3px;
  display: inline-block;
}
.current-status-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  background: var(--arcade-surface);
  border: 1px solid var(--arcade-border);
  border-radius: 5px;
  margin-bottom: 10px;
  font-family: 'Share Tech Mono', monospace;
  font-size: 0.7rem;
}
.current-status-label { color: var(--arcade-dim); text-transform: uppercase; font-size: 0.6rem; letter-spacing: 1px; }

/* ── Stats bar ── */
.stats-bar {
  display: flex;
  gap: 0;
  background: var(--arcade-panel);
  border: 1px solid var(--arcade-border);
  border-top: 2px solid var(--arcade-cyan);
  border-radius: 5px;
  margin-bottom: 16px;
  overflow: hidden;
}
.stat-item {
  flex: 1;
  text-align: center;
  padding: 8px 6px;
  border-right: 1px solid var(--arcade-border);
}
.stat-item:last-child { border-right: none; }
.stat-num { font-family:'Orbitron',monospace; font-size:1rem; font-weight:700; color:var(--arcade-yellow); display:block; }
.stat-label { font-family:'Share Tech Mono',monospace; font-size:0.58rem; color:var(--arcade-dim); text-transform:uppercase; letter-spacing:0.6px; }

/* ── Scanline overlay ── */
[data-testid="stMain"]::before {
  content:''; position:fixed; top:0;left:0;right:0;bottom:0;
  background:repeating-linear-gradient(0deg,rgba(0,0,0,0.025) 0px,rgba(0,0,0,0.025) 1px,transparent 1px,transparent 3px);
  pointer-events:none; z-index:9999;
}

/* ── Widget overrides ── */
[data-testid="stButton"] > button {
  font-family:'Share Tech Mono',monospace !important;
  font-size:0.73rem !important;
  background:var(--arcade-panel) !important;
  border:1px solid var(--arcade-border) !important;
  color:var(--arcade-text) !important;
  border-radius:4px !important;
  transition:all 0.12s !important;
}
[data-testid="stButton"] > button:hover {
  border-color:var(--arcade-cyan) !important;
  color:var(--arcade-cyan) !important;
  box-shadow:0 0 8px rgba(0,229,255,0.2) !important;
}
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] > div > div {
  background:var(--arcade-panel) !important;
  border-color:var(--arcade-border) !important;
  color:var(--arcade-text) !important;
  font-family:'Share Tech Mono',monospace !important;
  font-size:0.78rem !important;
}
.stExpander {
  border:1px solid var(--arcade-border) !important;
  background:var(--arcade-surface) !important;
  border-radius:5px !important;
}
[data-testid="stCaption"] {
  color:var(--arcade-subtext) !important;
  font-family:'Share Tech Mono',monospace !important;
  font-size:0.68rem !important;
}
[data-testid="stDivider"] { border-color:var(--arcade-border) !important; }
[data-testid="stDataFrame"] { border:1px solid var(--arcade-border) !important; border-radius:5px !important; }
</style>
""", unsafe_allow_html=True)

# ----------------------------
# Constants / Config
# ----------------------------
TZ = ZoneInfo("America/New_York")

CSV_PATH = "arcade_games_1978_2008_clean.csv"
DB_PATH = "game_state.db"

R2_PUBLIC_ROOT = "https://pub-04cb80aef9834a5d908ddf7538b7fffa.r2.dev"

APP_VERSION = (
    "1.8-ui • Arcade Retro aesthetic + Game Cards + Cleaner Details • "
    "Marquees (R2 root), Don't have ROM, Not playable, Want export • "
    "ADB on-demand • Supabase-first status persistence (SQLite fallback) • History Mode"
)

STATUS_WANT = "want_to_play"
STATUS_PLAYED = "played"
STATUS_NO_ROM = "dont_have_rom"
STATUS_NOT_PLAYABLE = "not_playable"

STATUS_LABELS = {
    None: "—",
    STATUS_WANT: "⏳ Want to Play",
    STATUS_PLAYED: "✅ Played",
    STATUS_NO_ROM: "🧩 Don't have ROM",
    STATUS_NOT_PLAYABLE: "🚫 Not playable",
}

STATUS_BADGE_CLASS = {
    None:               ("badge badge-none",    "—"),
    STATUS_WANT:        ("badge badge-want",    "WANT"),
    STATUS_PLAYED:      ("badge badge-played",  "PLAYED"),
    STATUS_NO_ROM:      ("badge badge-norom",   "NO ROM"),
    STATUS_NOT_PLAYABLE:("badge badge-noplay",  "NO PLAY"),
}

# ----------------------------
# OpenAI / History Mode
# ----------------------------
OPENAI_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

HISTORY_SYSTEM_PROMPT = """
You are an arcade video game historian and preservation expert.

Write a concise but insightful historical profile for a single arcade game.
Focus on:
- cabinet experience
- gameplay
- historical context
- commercial reception
- ports and legacy
- modern playability
- interesting facts

Rules:
- Be specific when facts are known.
- If a fact is uncertain or poorly documented, say that clearly.
- Do not invent production totals, sales figures, or development stories.
- If the title is obscure, explain that and still provide useful context.
- Write in clean markdown with short sections.
""".strip()

# ----------------------------
# UI Header
# ----------------------------
st.title("🕹️ Arcade Game Picker")
st.caption(
    "Cabinet-first discovery · find games you can actually play at home · 1978–2008"
)

# ----------------------------
# Cabinet profile + strict compatibility
# ----------------------------
CABINET_SUMMARY = (
    "Your cabinet: 4-way stick + 8-way stick, 6 buttons/player, NO spinner/trackball/lightgun/wheel, "
    "horizontal monitor (vertical OK)."
)

BLOCKED_GENRE_EXACT = {
    "trackball", "dial/paddle", "dial", "paddle",
    "lightgun shooter", "gambling", "casino", "quiz",
}
BLOCKED_GENRE_CONTAINS = ["driving", "racing", "pinball", "redemption"]
BLOCKED_TITLE_HINTS = [
    "lightgun", "light gun", "trackball", "spinner",
    "steering", "wheel", "pedal", "paddle",
]

# ----------------------------
# Helpers
# ----------------------------
def normalize_str(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip()

def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["rom", "game", "year", "company", "genre", "platform"]:
        if col not in df.columns:
            df[col] = ""
    df["rom"]      = df["rom"].map(normalize_str).str.lower()
    df["game"]     = df["game"].map(normalize_str)
    df["company"]  = df["company"].map(normalize_str)
    df["genre"]    = df["genre"].map(normalize_str)
    df["platform"] = df["platform"].map(normalize_str)
    df["year"]     = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["game", "year"]).copy()
    df["year"]     = df["year"].astype(int)
    df["_game_l"]     = df["game"].astype(str).str.lower()
    df["_genre_l"]    = df["genre"].astype(str).str.lower()
    df["_platform_l"] = df["platform"].astype(str).str.lower()
    df["_company_l"]  = df["company"].astype(str).str.lower()
    return df

def load_games_no_cache() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH)
    return ensure_columns(df)

def is_cabinet_compatible_strict(row: pd.Series) -> bool:
    genre    = normalize_str(row.get("genre", "")).strip().lower()
    title    = normalize_str(row.get("game", "")).strip().lower()
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
# Supabase
# ----------------------------
def _get_secret(name: str) -> str | None:
    try:
        val = st.secrets.get(name)
    except Exception:
        val = None
    if val is None:
        val = st.session_state.get(name)
    if isinstance(val, str):
        val = val.strip()
    return val or None

def supabase_enabled() -> bool:
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_ANON_KEY") or _get_secret("SUPABASE_KEY")
    return bool(url) and bool(key)

def _sb_base() -> str:
    return (_get_secret("SUPABASE_URL") or "").rstrip("/")

def _sb_key() -> str:
    return (_get_secret("SUPABASE_ANON_KEY") or _get_secret("SUPABASE_KEY") or "").strip()

def _sb_headers(extra: dict | None = None) -> dict:
    key = _sb_key()
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h

def supabase_get_all_statuses(table: str = "game_status") -> dict[str, str]:
    url = f"{_sb_base()}/rest/v1/{table}?select=rom,status"
    req = Request(url, headers=_sb_headers(), method="GET")
    with urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    out: dict[str, str] = {}
    if isinstance(data, list):
        for row in data:
            rom = (row.get("rom") or "").strip().lower()
            if rom:
                out[rom] = row.get("status")
    return out

def supabase_set_status(rom: str, status: str | None, table: str = "game_status") -> None:
    rom = (rom or "").strip().lower()
    if not rom:
        return
    base = _sb_base()
    headers = _sb_headers()
    if status is None:
        url = f"{base}/rest/v1/{table}?rom=eq.{quote(rom)}"
        req = Request(url, headers=headers, method="DELETE")
        with urlopen(req, timeout=15):
            return
    url = f"{base}/rest/v1/{table}"
    body = json.dumps({"rom": rom, "status": status}).encode("utf-8")
    headers2 = _sb_headers({"Prefer": "resolution=merge-duplicates"})
    req = Request(url, data=body, headers=headers2, method="POST")
    with urlopen(req, timeout=15):
        return

# ----------------------------
# SQLite fallback
# ----------------------------
def get_db() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_sqlite_db() -> None:
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS game_status (
            rom TEXT PRIMARY KEY,
            status TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS game_history (
            history_key TEXT PRIMARY KEY,
            history_md TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

def sqlite_get_all_statuses() -> dict[str, str]:
    conn = get_db()
    cur = conn.execute("SELECT rom, status FROM game_status")
    rows = cur.fetchall()
    conn.close()
    out = {}
    for rom, status in rows:
        if rom:
            out[str(rom).strip().lower()] = status
    return out

def sqlite_set_status(rom: str, status: str | None) -> None:
    rom = (rom or "").strip().lower()
    if not rom:
        return
    conn = get_db()
    if status is None:
        conn.execute("DELETE FROM game_status WHERE rom=?", (rom,))
    else:
        conn.execute("""
            INSERT INTO game_status (rom, status, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(rom) DO UPDATE SET status=excluded.status, updated_at=datetime('now')
        """, (rom, status))
    conn.commit()
    conn.close()

def sqlite_get_history(history_key: str) -> str | None:
    history_key = (history_key or "").strip().lower()
    if not history_key:
        return None
    conn = get_db()
    cur = conn.execute("SELECT history_md FROM game_history WHERE history_key=?", (history_key,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    val = row[0]
    return str(val).strip() if val else None

def sqlite_set_history(history_key: str, history_md: str) -> None:
    history_key = (history_key or "").strip().lower()
    history_md  = (history_md or "").strip()
    if not history_key or not history_md:
        return
    conn = get_db()
    conn.execute("""
        INSERT INTO game_history (history_key, history_md, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(history_key) DO UPDATE SET history_md=excluded.history_md, updated_at=datetime('now')
    """, (history_key, history_md))
    conn.commit()
    conn.close()

def sqlite_delete_history(history_key: str) -> None:
    history_key = (history_key or "").strip().lower()
    if not history_key:
        return
    conn = get_db()
    conn.execute("DELETE FROM game_history WHERE history_key=?", (history_key,))
    conn.commit()
    conn.close()

# ----------------------------
# OpenAI
# ----------------------------
def get_openai_api_key() -> str | None:
    key = _get_secret("OPENAI_API_KEY")
    if not key:
        key = os.getenv("OPENAI_API_KEY")
    return key or None

def get_openai_model() -> str:
    model = _get_secret("OPENAI_MODEL")
    if not model:
        model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    return model or DEFAULT_OPENAI_MODEL

def build_history_user_prompt(game_name, year, company, genre, platform, rom) -> str:
    return f"""
Provide a structured historical profile for this arcade game.

GAME: {game_name}
YEAR: {year}
COMPANY: {company or "Unknown"}
GENRE: {genre or "Unknown"}
ARCADE PLATFORM: {platform or "Unknown"}
ROM SHORT NAME: {rom or "Unknown"}

Please use these sections:

## Overview
## Gameplay & Controls
## Historical Context
## Commercial Performance
## Ports & Legacy
## Modern Playability
## Interesting Facts

Keep it concise, historically grounded, and readable.
""".strip()

def extract_text_from_responses_api(data: dict) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            ctype = content.get("type")
            if ctype in ("output_text", "text"):
                text = content.get("text", "")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    return "\n\n".join(parts).strip()

def generate_history_profile(game_name, year, company, genre, platform, rom) -> str:
    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "Missing OPENAI_API_KEY. Create .streamlit/secrets.toml or set OPENAI_API_KEY env var."
        )
    payload = {
        "model": get_openai_model(),
        "instructions": HISTORY_SYSTEM_PROMPT,
        "input": build_history_user_prompt(game_name, year, company, genre, platform, rom),
        "temperature": 0.6,
        "max_output_tokens": 1200,
        "store": False,
    }
    req = Request(
        OPENAI_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error ({e.code}): {detail}") from e
    except URLError as e:
        raise RuntimeError(f"Network error calling OpenAI: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error calling OpenAI: {e}") from e
    text = extract_text_from_responses_api(data)
    if not text:
        raise RuntimeError("OpenAI returned a response, but no text was found.")
    return text

# ----------------------------
# Unified status API
# ----------------------------
def get_all_statuses() -> dict[str, str]:
    if supabase_enabled():
        try:
            return supabase_get_all_statuses()
        except Exception:
            return sqlite_get_all_statuses()
    return sqlite_get_all_statuses()

def set_status(rom: str, status: str | None) -> None:
    if supabase_enabled():
        try:
            return supabase_set_status(rom, status)
        except Exception:
            return sqlite_set_status(rom, status)
    return sqlite_set_status(rom, status)

# ----------------------------
# Session state
# ----------------------------
def init_state():
    defaults = {
        "picked_rows": [],
        "selected_key": None,
        "adb_cache": {},
        "status_cache": {},
        "status_cache_loaded": False,
        "history_cache": {},
        "history_error_cache": {},
        "marquee_bytes_cache": {},
        "marquee_exists_cache": {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

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
# Links
# ----------------------------
def build_links(game_name: str):
    q = game_name.replace(" ", "+")
    return {
        "Gameplay (YouTube)":        f"https://www.youtube.com/results?search_query={q}+arcade+gameplay",
        "History / Legacy (search)": f"https://www.google.com/search?q={q}+arcade+history+legacy",
        "Controls / Moves (search)": f"https://www.google.com/search?q={q}+arcade+controls+buttons",
        "Manual / Instructions":     f"https://www.google.com/search?q={q}+arcade+manual+instructions",
        "Ports / Collections":       f"https://www.google.com/search?q={q}+arcade+collection+port",
    }

def game_key(row: pd.Series) -> str:
    rom = normalize_str(row.get("rom", "")).lower()
    if rom:
        return f"rom:{rom}"
    return (
        f"meta:{normalize_str(row.get('game',''))}|"
        f"{int(row.get('year',0))}|"
        f"{normalize_str(row.get('company',''))}"
    )

# ----------------------------
# Export
# ----------------------------
def build_want_to_play_txt(df: pd.DataFrame) -> str:
    want_roms = {rom for rom, status in st.session_state.status_cache.items() if status == STATUS_WANT}
    if not want_roms:
        return "No games marked as Want to Play."
    subset = df[df["rom"].isin(want_roms)].copy().sort_values(["year", "game"])
    lines: list[str] = []
    for _, row in subset.iterrows():
        lines.append(
            f"{row.get('game','')} ({row.get('year','')}) — "
            f"{row.get('company','')} — {row.get('genre','')} — ROM: {row.get('rom','')}"
        )
    return "\n".join(lines)

# ----------------------------
# Image helpers
# ----------------------------
def _st_image(data, *, caption: str | None = None):
    try:
        st.image(data, caption=caption, use_container_width=True)
    except TypeError:
        st.image(data, caption=caption, use_column_width=True)

def marquee_url(rom: str) -> str:
    rom = (rom or "").strip().lower()
    if not rom:
        return f"{R2_PUBLIC_ROOT}/default.png"
    return f"{R2_PUBLIC_ROOT}/{rom}.png"

def default_marquee_url() -> str:
    return f"{R2_PUBLIC_ROOT}/default.png"

def fetch_image_bytes(url: str, timeout_sec: int = 10) -> bytes | None:
    cache: dict = st.session_state.marquee_bytes_cache
    if url in cache:
        return cache[url]
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (ArcadeGamePicker)"}, method="GET")
        with urlopen(req, timeout=timeout_sec) as resp:
            b = resp.read()
        cache[url] = b
        return b
    except Exception:
        cache[url] = None
        return None

def show_marquee(rom: str, enabled: bool = True):
    if not enabled:
        return
    rom = (rom or "").strip().lower()
    if rom:
        b = fetch_image_bytes(marquee_url(rom), timeout_sec=10)
        if b:
            _st_image(b)
            return
    b2 = fetch_image_bytes(default_marquee_url(), timeout_sec=10)
    if b2:
        _st_image(b2)

# ----------------------------
# ADB integration
# ----------------------------
def adb_urls(rom: str):
    rom = (rom or "").strip().lower()
    params = {"ajax": "query_mame", "lang": "en", "game_name": rom}
    return {
        "page_https":    f"https://adb.arcadeitalia.net/?mame={rom}",
        "page_http":     f"http://adb.arcadeitalia.net/?mame={rom}",
        "scraper_https": "https://adb.arcadeitalia.net/service_scraper.php?" + urlencode(params),
        "scraper_http":  "http://adb.arcadeitalia.net/service_scraper.php?" + urlencode(params),
    }

def fetch_json_url(url: str, timeout_sec: int = 12) -> dict:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (ArcadeGamePicker; +https://streamlit.app)",
        "Accept": "application/json,text/plain,*/*",
    }, method="GET")
    with urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8", errors="replace").strip())
    return data if isinstance(data, dict) else {"_data": data}

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
    urls: list[str] = []
    def walk(x):
        if isinstance(x, dict):
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
        elif isinstance(x, str):
            s = x.strip()
            if (s.startswith("http://") or s.startswith("https://")) and re.search(r"\.(png|jpg|jpeg|webp)(\?.*)?$", s, re.IGNORECASE):
                urls.append(s)
    walk(obj)
    seen = set(); out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u); out.append(u)
    return out

def show_adb_block(rom: str):
    rom = (rom or "").strip().lower()
    if not rom:
        st.info("ADB details require a ROM short name; this entry has none.")
        return None
    urls = adb_urls(rom)
    st.markdown(f"**ADB:** [HTTP]({urls['page_http']}) · [HTTPS]({urls['page_https']})")

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        load_btn = st.button("📥 Load ADB", key=f"adb_load_{rom}")
    with c2:
        refresh_btn = st.button("♻️ Refresh", key=f"adb_refresh_{rom}")
    with c3:
        show_images = st.toggle("Show artwork", value=True, key=f"adb_img_{rom}")

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

    st.markdown("#### ADB Details")
    for k in ("title","description","manufacturer","year","genre","players","buttons","controls","rotation","status"):
        if k in data and data[k]:
            val = data[k]
            if isinstance(val, (dict, list)):
                st.write(f"**{k}:")
                st.json(val)
            else:
                st.write(f"**{k}:** {val}")

    if show_images:
        imgs = extract_image_urls(data)
        if imgs:
            st.markdown("#### Artwork")
            for u in imgs[:10]:
                _st_image(u)
        else:
            st.caption("No direct image URLs in the ADB response.")
    return data

# ----------------------------
# Badge HTML helper
# ----------------------------
def status_badge_html(status: str | None) -> str:
    cls, label = STATUS_BADGE_CLASS.get(status, ("badge badge-none", "—"))
    return f'<span class="{cls}">{label}</span>'

# ----------------------------
# Details panel (redesigned)
# ----------------------------
def show_game_details(row: pd.Series, *, show_marquees: bool):
    g        = normalize_str(row.get("game", ""))
    y        = int(row.get("year", 0))
    c        = normalize_str(row.get("company", ""))
    genre    = normalize_str(row.get("genre", ""))
    platform = normalize_str(row.get("platform", ""))
    rom      = normalize_str(row.get("rom", "")).lower()

    # Marquee
    show_marquee(rom, enabled=show_marquees)

    cur_status = status_for_rom(rom)
    bcls, blbl = STATUS_BADGE_CLASS.get(cur_status, ("badge badge-none", "—"))

    # Title + meta block
    st.markdown(f'<div class="detail-title">{g}</div>', unsafe_allow_html=True)

    meta_items = []
    if y:        meta_items.append(f'<div class="detail-meta-item"><strong>Year</strong><span>{y}</span></div>')
    if c:        meta_items.append(f'<div class="detail-meta-item"><strong>Company</strong><span>{c}</span></div>')
    if genre:    meta_items.append(f'<div class="detail-meta-item"><strong>Genre</strong><span>{genre}</span></div>')
    if platform: meta_items.append(f'<div class="detail-meta-item"><strong>Platform</strong><span>{platform}</span></div>')
    if rom:      meta_items.append(f'<div class="detail-meta-item"><strong>ROM</strong><span class="detail-rom">{rom}</span></div>')

    st.markdown(
        f'<div class="detail-meta-grid">{"".join(meta_items)}</div>',
        unsafe_allow_html=True
    )

    # Current status bar
    st.markdown(
        f'<div class="current-status-bar">'
        f'<span class="current-status-label">Status</span>'
        f'<span class="{bcls}">{blbl}</span>'
        f'</div>',
        unsafe_allow_html=True
    )

    # Status buttons — two rows of cleaner layout
    st.caption("Update status:")
    r1c1, r1c2 = st.columns(2)
    r2c1, r2c2, r2c3 = st.columns(3)

    with r1c1:
        if st.button("⏳ Want to Play", use_container_width=True, key=f"st_want_{rom}"):
            update_status(rom, STATUS_WANT); st.rerun()
    with r1c2:
        if st.button("✅ Played", use_container_width=True, key=f"st_played_{rom}"):
            update_status(rom, STATUS_PLAYED); st.rerun()
    with r2c1:
        if st.button("🧩 No ROM", use_container_width=True, key=f"st_norom_{rom}"):
            update_status(rom, STATUS_NO_ROM); st.rerun()
    with r2c2:
        if st.button("🚫 Can't Play", use_container_width=True, key=f"st_np_{rom}"):
            update_status(rom, STATUS_NOT_PLAYABLE); st.rerun()
    with r2c3:
        if st.button("🧽 Clear", use_container_width=True, key=f"st_clear_{rom}"):
            update_status(rom, None); st.rerun()

    st.divider()

    # History Mode
    with st.expander("🧠 History Mode", expanded=False):
        history_key = (rom or f"{g}|{y}|{c}").strip().lower()
        history_safe_key = re.sub(r"[^a-z0-9_:-]+", "_", history_key)
        existing_history = st.session_state.history_cache.get(history_key)
        existing_error   = st.session_state.history_error_cache.get(history_key)

        if not existing_history:
            db_history = sqlite_get_history(history_key)
            if db_history:
                existing_history = db_history
                st.session_state.history_cache[history_key] = db_history

        st.caption("Generate a historical profile with OpenAI. Cached locally in SQLite.")

        h1, h2, h3 = st.columns([1, 1, 1])
        with h1:
            generate_btn = st.button("🧠 Generate",    use_container_width=True, key=f"hist_gen_{history_safe_key}")
        with h2:
            refresh_btn  = st.button("♻️ Regenerate", use_container_width=True, key=f"hist_refresh_{history_safe_key}")
        with h3:
            clear_btn    = st.button("🧽 Clear saved", use_container_width=True, key=f"hist_clear_{history_safe_key}")

        if clear_btn:
            sqlite_delete_history(history_key)
            st.session_state.history_cache.pop(history_key, None)
            st.session_state.history_error_cache.pop(history_key, None)
            existing_history = None; existing_error = None
            st.rerun()

        if refresh_btn:
            st.session_state.history_cache.pop(history_key, None)
            st.session_state.history_error_cache.pop(history_key, None)
            existing_history = None; existing_error = None

        if generate_btn or refresh_btn:
            with st.spinner("Generating history profile..."):
                try:
                    history_md = generate_history_profile(g, y, c, genre, platform, rom)
                    sqlite_set_history(history_key, history_md)
                    st.session_state.history_cache[history_key] = history_md
                    st.session_state.history_error_cache.pop(history_key, None)
                    existing_history = history_md; existing_error = None
                except Exception as e:
                    existing_error = str(e)
                    st.session_state.history_error_cache[history_key] = existing_error

        if existing_error:
            st.error(existing_error)
        if existing_history:
            st.markdown(existing_history)
        else:
            st.info("No saved history profile yet. Hit Generate above.")

    # ADB + Research collapsed together
    with st.expander("📚 ADB details + artwork (on-demand)", expanded=False):
        show_adb_block(rom)

    with st.expander("🔗 Research links", expanded=False):
        for name, url in build_links(g).items():
            st.write(f"- [{name}]({url})")

# ----------------------------
# Boot
# ----------------------------
init_state()
init_sqlite_db()
load_status_cache_once()

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
# Sidebar
# ----------------------------
st.sidebar.header("🎛️ Controls")
st.sidebar.caption(APP_VERSION)

strict_mode = st.sidebar.toggle("STRICT: only cabinet-playable games", value=True)

st.sidebar.subheader("Status filters")
hide_played       = st.sidebar.toggle("Hide ✅ Played",              value=True)
only_want         = st.sidebar.toggle("Show only ⏳ Want to Play",   value=False)
only_played       = st.sidebar.toggle("Show only ✅ Played",         value=False)
show_no_rom       = st.sidebar.toggle("Include 🧩 Don't have ROM",   value=False)
show_not_playable = st.sidebar.toggle("Include 🚫 Not playable",     value=False)

st.sidebar.divider()
show_marquees = st.sidebar.toggle("Show marquees", value=True)

st.sidebar.divider()
want_count = sum(1 for s in st.session_state.status_cache.values() if s == STATUS_WANT)
st.sidebar.download_button(
    label=f"📤 Export Want to Play ({want_count})",
    data=build_want_to_play_txt(df),
    file_name="arcade_want_to_play.txt",
    mime="text/plain",
    use_container_width=True,
)

st.sidebar.divider()
search_name = st.sidebar.text_input("Search (name or ROM)", "")

with st.sidebar.expander("Advanced filters", expanded=False):
    years = st.slider("Year range", 1978, 2008, (1978, 2008))
    platforms = sorted(df["platform"].replace("", pd.NA).dropna().unique().tolist())
    genres    = sorted(df["genre"].replace("", pd.NA).dropna().unique().tolist())
    platform_choice = st.multiselect("Platform (optional)", platforms)
    genre_choice    = st.multiselect("Genre (optional)", genres)

# ----------------------------
# Filtering
# ----------------------------
base = df[(df["year"] >= years[0]) & (df["year"] <= years[1])].copy()
if platform_choice:
    base = base[base["platform"].isin(platform_choice)]
if genre_choice:
    base = base[base["genre"].isin(genre_choice)]
if strict_mode:
    base = base[base.apply(is_cabinet_compatible_strict, axis=1)]

def keep_by_status(row: pd.Series) -> bool:
    rom = normalize_str(row.get("rom", "")).lower()
    s   = status_for_rom(rom)
    if only_played:
        return s == STATUS_PLAYED
    if only_want:
        return s == STATUS_WANT
    if hide_played and s == STATUS_PLAYED:
        return False
    if (not show_no_rom) and s == STATUS_NO_ROM:
        return False
    if (not show_not_playable) and s == STATUS_NOT_PLAYABLE:
        return False
    return True

base = base[base.apply(keep_by_status, axis=1)].copy()
base = base.sort_values(["year", "game"]).reset_index(drop=True)

if search_name.strip():
    s = search_name.strip().lower()
    hits = base[
        base["_game_l"].str.contains(s, na=False)
        | base["rom"].astype(str).str.lower().str.contains(s, na=False)
    ].copy()
else:
    hits = base.copy()

# ----------------------------
# Stats bar (top of main area)
# ----------------------------
total_games   = len(df)
total_visible = len(hits)
played_count  = sum(1 for s in st.session_state.status_cache.values() if s == STATUS_PLAYED)
want_count_v  = sum(1 for s in st.session_state.status_cache.values() if s == STATUS_WANT)

st.markdown(f"""
<div class="stats-bar">
  <div class="stat-item"><span class="stat-num">{total_games:,}</span><span class="stat-label">Total</span></div>
  <div class="stat-item"><span class="stat-num">{total_visible:,}</span><span class="stat-label">Showing</span></div>
  <div class="stat-item"><span class="stat-num">{played_count}</span><span class="stat-label">Played</span></div>
  <div class="stat-item"><span class="stat-num">{want_count_v}</span><span class="stat-label">Want</span></div>
</div>
""", unsafe_allow_html=True)

# ----------------------------
# Two-panel layout
# ----------------------------
left, right = st.columns([1.15, 1.0], gap="large")

with left:
    st.subheader("🎲 Discover")

    c1, c2 = st.columns([1, 1])
    with c1:
        pick_random = st.button("🎲 Random", use_container_width=True)
    with c2:
        clear_sel = st.button("🧹 Clear selection", use_container_width=True)

    if clear_sel:
        st.session_state.picked_rows = []
        st.session_state.selected_key = None
        st.rerun()

    # Game of the Day
    st.markdown("#### 📆 Game of the Day")
    now  = datetime.now(TZ)
    seed = int(now.strftime("%Y")) * 1000 + int(now.strftime("%j"))

    if len(hits) > 0:
        gotd = hits.iloc[seed % len(hits)]
        gotd_status = status_for_rom(normalize_str(gotd.get("rom", "")).lower())
        bcls, blbl = STATUS_BADGE_CLASS.get(gotd_status, ("badge badge-none", "—"))
        st.markdown(
            f'<div class="game-card">'
            f'<div class="game-card-title">{gotd["game"]}</div>'
            f'<div class="game-card-meta">'
            f'<span>📅 {gotd["year"]}</span>'
            f'<span>🏭 {gotd.get("company","")}</span>'
            f'<span class="{bcls}">{blbl}</span>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        if st.button("▶ Open Game of the Day", use_container_width=True):
            st.session_state.selected_key = game_key(gotd)
            st.rerun()
    else:
        st.caption("No Game of the Day with current filters.")

    if pick_random:
        if len(hits) == 0:
            st.warning("No games match your current filters. Widen filters.")
        else:
            row = hits.sample(1).iloc[0]
            st.session_state.selected_key = game_key(row)
            st.rerun()

    st.divider()

    with st.expander("Browse & 10 Picks", expanded=True):
        st.caption(f"**{len(hits):,}** games match current filters")

        c3, c4 = st.columns([1, 1])
        with c3:
            pick_10 = st.button("🎯 10 Picks", use_container_width=True)
        with c4:
            clear_picks = st.button("🧽 Clear Picks", use_container_width=True)

        if clear_picks:
            st.session_state.picked_rows = []
            st.rerun()

        if pick_10:
            if len(hits) == 0:
                st.warning("No games match your current filters.")
            else:
                n = min(10, len(hits))
                sample = hits.sample(n).copy()
                st.session_state.picked_rows = sample.to_dict("records")
                st.session_state.selected_key = game_key(pd.Series(st.session_state.picked_rows[0]))
                st.rerun()

        # ── Game Cards browse list ──
        st.markdown("##### 📜 Browse")

        if len(hits) == 0:
            st.info("No results. Adjust filters or search.")
        else:
            # Show top 80 as cards; selectbox for full list
            card_limit = 80
            card_rows  = hits.head(card_limit)

            for _, row in card_rows.iterrows():
                rom_val  = normalize_str(row.get("rom", "")).lower()
                s        = status_for_rom(rom_val)
                bcls, blbl = STATUS_BADGE_CLASS.get(s, ("badge badge-none", "—"))
                genre_v  = row.get("genre", "")
                card_html = (
                    f'<div class="game-card">'
                    f'<div class="game-card-title">{row["game"]}</div>'
                    f'<div class="game-card-meta">'
                    f'<span>📅 {int(row["year"])}</span>'
                    f'<span>🏭 {row.get("company","")}</span>'
                    f'<span>🎮 {genre_v}</span>'
                    f'<span class="{bcls}">{blbl}</span>'
                    f'</div></div>'
                )
                st.markdown(card_html, unsafe_allow_html=True)
                if st.button("▶ Open", key=f"card_open_{rom_val}_{int(row['year'])}", use_container_width=False):
                    st.session_state.selected_key = game_key(row)
                    st.rerun()

            if len(hits) > card_limit:
                st.caption(f"Showing first {card_limit} of {len(hits):,}. Use search or filters to narrow down.")

        # Selectbox for full list
        st.markdown("##### Or select from full list")
        view = hits[["rom", "game", "year", "company", "genre", "platform"]].copy()
        view["status"] = view["rom"].apply(lambda r: STATUS_LABELS.get(status_for_rom(str(r).lower()), "—"))
        if len(view) > 0:
            labels = (
                view["game"].astype(str) + " — " +
                view["year"].astype(str) + " — " +
                view["company"].astype(str) + " — " +
                view["status"].astype(str)
            )
            selected_label = st.selectbox("Pick from results", labels, key="browse_select")
            idx = labels[labels == selected_label].index[0]
            selected_row = view.loc[idx]
            if st.button("➡️ Open selected", use_container_width=True):
                st.session_state.selected_key = game_key(selected_row)
                st.rerun()

        # 10 picks
        if st.session_state.picked_rows:
            st.markdown("##### 🎯 Your 10 Picks")
            pick_df = pd.DataFrame(st.session_state.picked_rows)
            pick_df = pick_df[["rom", "game", "year", "company", "genre", "platform"]].copy()
            for i, r in pick_df.iterrows():
                rom_v    = normalize_str(r.get("rom", "")).lower()
                s        = status_for_rom(rom_v)
                bcls, blbl = STATUS_BADGE_CLASS.get(s, ("badge badge-none", "—"))
                card_html = (
                    f'<div class="game-card">'
                    f'<div class="game-card-title">{r["game"]}</div>'
                    f'<div class="game-card-meta">'
                    f'<span>📅 {int(r["year"])}</span>'
                    f'<span class="{bcls}">{blbl}</span>'
                    f'</div></div>'
                )
                st.markdown(card_html, unsafe_allow_html=True)
                if st.button("▶ Open", key=f"pick_{i}", use_container_width=False):
                    st.session_state.selected_key = game_key(r)
                    st.rerun()

with right:
    st.subheader("🧾 Details")
    if not st.session_state.selected_key:
        st.markdown("""
        <div style="text-align:center; padding:40px 20px; color:#6b6b8a; font-family:'Share Tech Mono',monospace;">
            <div style="font-size:2.5rem; margin-bottom:12px;">🕹️</div>
            <div style="font-size:0.8rem; letter-spacing:1px; text-transform:uppercase;">
                Hit 🎲 Random or pick from the browse list
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        key = st.session_state.selected_key
        if key.startswith("rom:"):
            rom = key.split("rom:", 1)[1]
            match = df[df["rom"] == rom]
            if len(match) == 0:
                st.warning("Selected game not found in dataset.")
            else:
                show_game_details(match.iloc[0], show_marquees=show_marquees)
        else:
            try:
                _, meta = key.split("meta:", 1)
                title, year_str, company = meta.split("|", 2)
                year  = int(year_str)
                match = df[(df["game"] == title) & (df["year"] == year) & (df["company"] == company)]
                if len(match) == 0:
                    st.warning("Selected game not found in dataset.")
                else:
                    show_game_details(match.iloc[0], show_marquees=show_marquees)
            except Exception:
                st.warning("Could not resolve selection key.")
