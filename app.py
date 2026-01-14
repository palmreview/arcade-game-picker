import streamlit as st
import pandas as pd

st.set_page_config(page_title="Arcade Game Picker", layout="centered")

st.title("🕹️ Arcade Game Picker (1978–2008)")
st.caption("Filter, pick a random game, or list all matching games.")

@st.cache_data
def load_games():
    df = pd.read_csv("arcade_games_1978_2008_clean.csv")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["game", "year"]).copy()
    df["year"] = df["year"].astype(int)

    # Optional: ensure columns exist
    for col in ["company", "genre", "platform"]:
        if col not in df.columns:
            df[col] = ""

    return df

df = load_games()

# ----------------------------
# Filters
# ----------------------------
years = st.slider("Year range", 1978, 2008, (1978, 2008))

platforms = sorted(df["platform"].dropna().astype(str).unique().tolist())
genres = sorted(df["genre"].dropna().astype(str).unique().tolist())

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

st.write(f"Games available: **{len(filtered):,}**")

# ----------------------------
# Buttons
# ----------------------------
btn1, btn2 = st.columns(2)

with btn1:
    pick_random = st.button("🎲 Pick a Random Game")

with btn2:
    # Toggle show/hide list using session_state
    if "show_list" not in st.session_state:
        st.session_state.show_list = False

    if st.button("📜 Show/Hide List"):
        st.session_state.show_list = not st.session_state.show_list

# ----------------------------
# Random result
# ----------------------------
if pick_random:
    if len(filtered) == 0:
        st.warning("No games match your filters. Try widening them.")
    else:
        pick = filtered.sample(1).iloc[0]
        game = str(pick["game"])
        year = int(pick["year"])
        company = str(pick.get("company", ""))
        genre = str(pick.get("genre", ""))
        platform = str(pick.get("platform", ""))

        st.subheader(game)
        st.write(f"**Year:** {year}")
        if company:
            st.write(f"**Company:** {company}")
        if genre:
            st.write(f"**Genre:** {genre}")
        if platform:
            st.write(f"**Platform:** {platform}")

        q = game.replace(" ", "+")
        st.markdown(f"▶ **Gameplay:** https://www.youtube.com/results?search_query={q}+arcade")
        st.markdown(f"🕹️ **MAME info:** https://www.google.com/search?q={q}+MAME")
        st.markdown(f"📖 **History:** https://www.google.com/search?q={q}+arcade+history")

# ----------------------------
# List all matching games
# ----------------------------
if st.session_state.show_list:
    st.subheader("📜 Matching Games")

    # Optional: quick text filter within the filtered results
    search = st.text_input("Search within results (optional)", "")

    view = filtered[["game", "year", "company", "genre", "platform"]].copy()
    view = view.sort_values(["year", "game"])

    if search.strip():
        s = search.strip().lower()
        view = view[
            view["game"].astype(str).str.lower().str.contains(s)
            | view["company"].astype(str).str.lower().str.contains(s)
            | view["genre"].astype(str).str.lower().str.contains(s)
            | view["platform"].astype(str).str.lower().str.contains(s)
        ]

    st.write(f"Showing: **{len(view):,}** games")
    st.dataframe(view, use_container_width=True, height=500)

    # Download the filtered list
    csv_bytes = view.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download this filtered list (CSV)",
        data=csv_bytes,
        file_name="arcade_filtered_games.csv",
        mime="text/csv",
    )
