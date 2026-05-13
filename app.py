import json
import logging
from pathlib import Path

import chromadb
import streamlit as st

from src.assistant import CineMatchAssistant
from src.config import CHROMA_DB_PATH, DATA_DIR

logging.basicConfig(level=logging.WARNING)

CATALOG_PATH = Path(DATA_DIR) / "catalog.json"
COLLECTION_NAME = "cinematch_movies"
INITIAL_MESSAGE = {
    "role": "assistant",
    "text": "¡Hola! Soy CineMatch, tu crítico de cine. ¿Qué te provoca ver hoy?",
    "recommendations": [],
}


@st.cache_resource(show_spinner="Inicializando CineMatch…")
def get_assistant() -> CineMatchAssistant:
    return CineMatchAssistant()


@st.cache_resource
def get_catalog_count() -> int:
    try:
        with CATALOG_PATH.open(encoding="utf-8") as f:
            return len(json.load(f))
    except Exception:
        return 0


@st.cache_resource
def get_embeddings_count() -> int:
    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        collection = client.get_or_create_collection(COLLECTION_NAME)
        return collection.count()
    except Exception:
        return 0


def render_movie_card(movie: dict) -> None:
    poster_url = movie.get("poster_url", "")
    if poster_url:
        st.image(poster_url, use_container_width=True)
    else:
        st.markdown("🎬")

    title = movie.get("title") or "Sin título"
    st.markdown(f"**{title}**")

    year = movie.get("year")
    runtime = movie.get("runtime")
    if year and runtime:
        st.caption(f"{year} · {runtime} min")
    elif year:
        st.caption(str(year))

    vote_average = movie.get("vote_average")
    if vote_average is not None:
        st.caption(f"⭐ {vote_average:.1f}")
    else:
        st.caption("⭐ —")

    genres = movie.get("genres", "")
    if genres:
        st.caption(f"🎭 {genres}")

    with st.expander("Sinopsis"):
        overview = movie.get("overview") or "Sin sinopsis disponible."
        st.write(overview)
        director = movie.get("director", "")
        if director:
            st.markdown(f"Director: **{director}**")
        movie_id = movie.get("id", "")
        if movie_id:
            st.link_button("Ver en TMDB", f"https://www.themoviedb.org/movie/{movie_id}")


def render_recommendations(recs: list[dict]) -> None:
    cols = st.columns(3)
    for i, movie in enumerate(recs[:6]):
        with cols[i % 3]:
            render_movie_card(movie)


# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="CineMatch",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="expanded",
)

assistant = get_assistant()

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("# 🎬 CineMatch")
    st.markdown(
        "Asistente conversacional de cine potenciado por Gemini. "
        "Pregúntame por estado de ánimo, género, director o película concreta."
    )

    st.divider()

    st.markdown("**Sobre el proyecto**")
    st.markdown("Asistente conversacional de cine")
    st.markdown("Universidad de Pamplona")
    st.markdown("Santiago De Avila Quintero")

    st.divider()

    st.markdown("**Sistema**")
    st.metric("Películas en catálogo", get_catalog_count())
    st.metric("Embeddings indexados", get_embeddings_count())

    st.divider()

    if st.button("🔄 Nueva conversación"):
        st.session_state.messages = [dict(INITIAL_MESSAGE)]
        assistant._history = []
        assistant._shown_ids = set()
        st.rerun()

# ── Session state ──────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = [dict(INITIAL_MESSAGE)]

# ── Main area ──────────────────────────────────────────────────────────────────

st.title("🎬 CineMatch")
st.caption("Tu crítico de cine personal")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])
        if msg.get("recommendations"):
            render_recommendations(msg["recommendations"])

prompt = st.chat_input("Cuéntame qué quieres ver…")

if prompt:
    st.session_state.messages.append({
        "role": "user",
        "text": prompt,
        "recommendations": [],
    })

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Pensando…"):
            try:
                response = assistant.chat(prompt)
            except Exception as e:
                st.error(f"Hubo un error: {e}")
                response = {
                    "text": "Lo siento, tuve un problema. ¿Puedes intentar de nuevo?",
                    "recommendations": [],
                }

        st.markdown(response["text"])
        if response.get("recommendations"):
            render_recommendations(response["recommendations"])

    st.session_state.messages.append({
        "role": "assistant",
        "text": response["text"],
        "recommendations": response.get("recommendations", []),
    })
