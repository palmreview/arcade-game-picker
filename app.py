import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
st.set_page_config(page_title="Arcade Game Picker", layout="centered")

st.title("🕹️ Arcade Game Picker (1978–2008)")
st.caption(
    "Filter, pick random, list results, favorite games, search by name, and see a Game of the Day. "
    "Artwork is temporarily disabled."
)

# ----------------------------
# Constants
# ----------------------------
TZ = ZoneInfo("America/New_York")


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

    df["rom"] = df["rom"].map(normalize_str).str.lower()
    df["game"] = df["game"].map(normalize_str)
    df["company"] = df["company"].map(normalize_str)
    df["genre"] = df["genre"].map(normalize_str)
    df["platform"] = df["platform"].map(normalize_str)

    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["game", "year"]).copy()
    df["year"] = df["year"].astype(int)
    return df


@st.cache_data
def load_games():
    df = pd.read_csv("arcade_games_1978_2008_clean.csv")
    return ensure_columns(df)


def build_links(game_name: str):
    q = game_name.replace(" ", "+")
    return {
        "Gameplay (YouTube)": f"https://www.youtube.com/results?search_query={q}+arcade",
        "MAME info (search)": f"https://www.google.com/search?q={q}+MAME",
        "History (search)": f"https://www.google.com/search?q={q}+arcade+history",
    }


def init_state():
    if "show_list" not in st.session_state:
        st.session_state.show_list = False
    if "favorites" not in st.session_state:
        st.session_state.favorites = []


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


def show_game_details(row: pd.Series, section_title: str = None):
    """Artwork removed for now; shows metadata + favorite button + research links."""
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


# ----------------------------
# App state + data
# ----------------------------
init_state()
df = load_games()

# ----------------------------
# Sidebar: Favorites import/export (per-device via download/upload)
# ----------------------------
st.sidebar.header("⭐ Favorites (Per Device)")

fav_count = len(st.session_state.favorites)
st.sidebar.write(f"Favorites in this session: **{fav_count}**")

fav_json = json.dumps({"favorites": st.session_state.favorites}, indent=2).encode("utf-8")
st.sidebar.download_button(
    "⬇️ Download Favorites (JSON)",
    data=fav_json,
    file_name="arcade_favorites.json",
    mime="application/json",
)

uploaded = st.sidebar.file_uploader("⬆️ Import Favorites (JSON)", type=["json"])
if uploaded is not None:
    try:
        data = json.loads(uploaded.read().decode("utf-8"))
        favs = data.get("favorites", [])
        if isinstance(favs, list):
            st.session_state.favorites = list(dict.fromkeys([str(x) for x in favs]))
            st.sidebar.success("Favorites imported!")
            st.rerun()
        else:
            st.sidebar.error("Invalid favorites format.")
    except Exception:
        st.sidebar.error("Could not read that JSON file.")

if st.sidebar.button("🗑️ Clear Favorites"):
    st.session_state.favorites = []
    st.sidebar.success("Favorites cleared.")
    st.rerun()

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
# Game of the Day (FIXED)
# ----------------------------
st.header("📆 Game of the Day")

# FIX: Use local date (America/New_York) and incorporate day-of-year + year
# to avoid edge cases where a cached value or time zone mismatch keeps it unchanged.
now = datetime.now(TZ)
seed = int(now.strftime("%Y")) * 1000 + int(now.strftime("%j"))  # e.g., 2026*1000 + day_of_year

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

        fav_csv = fav_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download Favorites (CSV)",
            data=fav_csv,
            file_name="arcade_favorites.csv",
            mime="text/csv",
        )
