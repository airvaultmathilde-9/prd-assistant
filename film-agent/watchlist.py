"""Page « 🕒 À voir » : les films que je mets de côté, puis que je range dans « Mes films » une fois vus.

La liste, c'est le statut « Plus tard » de la mémoire : le bouton 🕒 sous une carte de
recommandation y ajoute un film, et l'agent sait qu'il peut me le reproposer.
« ✅ Je l'ai vu » ouvre la fiche (note, année, commentaire) : le film rejoint mes notes
Pinecone et quitte la liste. Aucun appel à Claude ici : seulement TMDB et Pinecone (gratuits).
"""

from __future__ import annotations

from html import escape

import streamlit as st

import my_films
from memory import Memory
from recommend import format_runtime
from tmdb_client import TMDBError

state = st.session_state
ACCESS_LABELS = {"abonnement": "inclus dans ton abonnement", "gratuit": "gratuit",
                 "location": "en location", "achat": "à l'achat", "autre_abonnement": "autre abonnement"}


def _info(tmdb_id: int) -> dict:
    """Affiche, durée, réalisation et où le voir : lus une fois dans TMDB, puis gardés."""
    cache = state.setdefault("wl_info", {})
    if tmdb_id not in cache:
        tmdb, _ = my_films._clients()
        try:
            details = tmdb.get_movie_details(tmdb_id)
            options = tmdb.get_watch_providers(tmdb_id).get("options") or []
        except TMDBError:
            details, options = {}, []
        cache[tmdb_id] = {**details, "best": options[0] if options else None}
    return cache[tmdb_id]


def _close() -> None:
    state.pop("wl_dialog", None)
    state.pop("wl_results", None)


@st.dialog("Je l'ai vu : ranger dans mes films", width="medium", on_dismiss=_close)
def seen_dialog(tmdb_id: int, title: str) -> None:
    st.markdown(f"**{escape(title)}** quitte ta liste « À voir » et rejoint tes notes : "
                "l'agent s'en servira pour comprendre tes goûts.")
    note, comment, year = my_films._rating_fields(4.0, "", None, f"wl-seen-{tmdb_id}")
    st.caption("3/5 ou plus : « vu et aimé ». Moins : « vu et pas aimé ».")
    cancel, save = st.columns(2)
    if cancel.button("Annuler", width="stretch"):
        _close()
        st.rerun()
    if save.button("Ranger dans mes films", type="primary", width="stretch"):
        if my_films._save(tmdb_id=tmdb_id, note=note, commentaire=comment, annee_visionnage=year):
            _close()
            st.rerun()


@st.dialog("Mettre un film de côté", width="medium", on_dismiss=_close)
def add_dialog() -> None:
    query = st.text_input("Titre du film", placeholder="Ex. : Anatomie d'une chute", key="wl-query")
    if st.button("🔎 Chercher dans TMDB", width="stretch") and query.strip():
        try:
            state.wl_results = my_films._clients()[0].search_movies(query.strip(), limit=6)
        except Exception as exc:
            st.error(f"Recherche impossible ({type(exc).__name__}).")
    results = state.get("wl_results")
    if results is None:
        return
    if not results:
        st.info("Aucun film trouvé : essaie le titre original.")
        return
    choice = st.radio("Lequel ?", results, key="wl-choice",
                      format_func=lambda m: f"{m['title']} ({m.get('year') or '?'})")
    status = Memory().status_of(choice["tmdb_id"])
    if status == "plus_tard":
        st.info("Il est déjà dans ta liste.")
        return
    if status in ("vu_aime", "vu_pas_aime"):
        st.warning("Tu l'as déjà vu : il est dans « Mes films ».")
        return
    if st.button("🕒 Mettre de côté", type="primary", width="stretch"):
        Memory().set_feedback(choice["tmdb_id"], choice["title"], "plus_tard")
        state.mf_toast = f"« {choice['title']} » mis de côté."
        _close()
        st.rerun()


def render() -> None:
    st.title("🕒 À voir")
    if "mf_toast" in state:
        st.toast(state.pop("mf_toast"), icon="✅")
    memory = Memory()
    later = sorted(memory.films_with("plus_tard"),
                   key=lambda f: memory.feedback[str(f[0])].get("date", ""), reverse=True)
    st.caption(f"{len(later)} film{'s' if len(later) > 1 else ''} mis de côté · ajoute-en avec le bouton 🕒 "
               "sous une recommandation, ou ici. Une fois vu, range-le dans « Mes films ».")
    if st.button("➕ Mettre un film de côté", type="primary"):
        state.wl_dialog = ("add", None)
    if not later:
        st.info("Ta liste est vide pour l'instant.")

    for tmdb_id, title in later:
        info = _info(tmdb_id)
        with st.container(key=f"wl-row-{tmdb_id}", border=True):
            poster, text, actions = st.columns([1, 6, 3], vertical_alignment="center")
            if info.get("poster_url"):
                poster.image(info["poster_url"])
            meta = [format_runtime(info.get("runtime_min")), ", ".join((info.get("directors") or [])[:2]),
                    ", ".join((info.get("genres") or [])[:2])]
            best = info.get("best")
            where = (f"📺 {best['platform']} · {ACCESS_LABELS.get(best['access'], best['access'])}"
                     if best else "📺 Pas disponible chez toi pour l'instant")
            added = memory.feedback[str(tmdb_id)].get("date", "")
            text.markdown(
                f'<div class="mf-title">{escape(info.get("title") or title)} '
                f'<span class="year">{info.get("year") or ""}</span></div>'
                f'<div class="meta">{escape(" · ".join(m for m in meta if m))}</div>'
                f'<div class="watch">{escape(where)}</div>'
                + (f'<div class="meta">Mis de côté le {added[8:10]}/{added[5:7]}/{added[:4]}</div>' if added else ""),
                unsafe_allow_html=True)
            if best and best.get("link"):
                actions.link_button(f"▶️ {best['platform']}", best["link"], width="stretch")
            if actions.button("✅ Je l'ai vu", key=f"wl-seen-btn-{tmdb_id}", type="primary", width="stretch"):
                state.wl_dialog = ("seen", tmdb_id)
            if actions.button("Retirer", key=f"wl-del-btn-{tmdb_id}", width="stretch",
                              help="Retirer de la liste, sans le noter"):
                Memory().clear_feedback(tmdb_id)
                st.rerun()

    kind, film_id = state.get("wl_dialog", (None, None))
    titles = dict(later)
    if kind == "add":
        add_dialog()
    elif kind == "seen" and film_id in titles:
        seen_dialog(film_id, titles[film_id])
