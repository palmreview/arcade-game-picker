import streamlit as st
import pandas as pd

st.set_page_config(page_title="Arcade Game Picker", layout="centered")

st.title("🕹️ Arcade Game Picker (1978–2008)")
st.caption("Tap the button to get a random arcade game to research and play.")

@st.cache_data
def load_games():
    df = pd.read_csv("arcade_games_1978_2008_clean.csv")
    # basic cleanup
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["game", "year"]).copy()
    df["year"] = df["year"].astype(int)
    return df

df = load_games()

# Optional filters
years = st.slider("Year range", 1978, 2008, (1978, 2008))
platforms = sorted(df["platform"].dropna().unique().tolist())
genres = sorted(df["genre"].dropna().unique().tolist())

col1, col2 = st.columns(2)
with col1:
    platform_choice = st.multiselect("Platform (optional)", platforms)
with col2:
    genre_choice = st.multiselect("Genre (optional)", genres)

filtered = df[(df["year"] >= years[0]) & (df["year"] <= years[1])]

if platform_choice:
    filtered = filtered[filtered["platform"].isin(platform_choice)]
if genre_choice:
    filtered = filtered[filtered["genre"].isin(genre_choice)]

st.write(f"Games available: **{len(filtered):,}**")

if st.button("🎲 Pick a Random Game"):
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
