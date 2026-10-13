"""Page « 🎞️ Mes films » : tous mes films notés (Pinecone), avec ajout, modification, suppression.

Aucun appel à Claude ici : seulement TMDB (pour trouver un film) et Pinecone (gratuits).
Je ne saisis que ce qui vient de moi : note, commentaire, année de visionnage.
"""

from __future__ import annotations

from datetime import date
from html import escape

import streamlit as st

from config import ConfigError, get_settings
from memory import Memory
from ratings_store import RatingsStore
from seen_films import delete_rating, save_rating, to_csv
from tmdb_client import TMDBClient

state = st.session_state

NOTE_FILTERS = {
    "Toutes les notes": lambda n: True,
    "❤️ Aimés (4 et plus)": lambda n: n >= 4,
    "😐 Moyens (2,5 à 3,5)": lambda n: 2.5 <= n < 4,
    "👎 Pas aimés (2 et moins)": lambda n: n <= 2,
}
SORTS = {
    "Note (la plus haute d'abord)": (lambda f: (-f.get("note", 0), f.get("titre", "").lower())),
    "Vus récemment": (lambda f: (-(f.get("annee_visionnage") or 0), f.get("titre", "").lower())),
    "Titre (A → Z)": (lambda f: f.get("titre", "").lower()),
    "Année de sortie (récents d'abord)": (lambda f: (-(f.get("annee_sortie") or 0), f.get("titre", "").lower())),
}


def _clients() -> tuple[TMDBClient, RatingsStore]:
    settings = get_settings()
    return TMDBClient(settings.tmdb_api_key), RatingsStore(settings.pinecone_api_key, settings.pinecone_index)


def load_films(force: bool = False) -> dict[str, dict]:
    """Mes films, lus dans Pinecone une fois puis gardés en mémoire de la page.

    Après un ajout ou une modification, on met aussi à jour cette copie : Pinecone met
    quelques secondes à refléter les changements dans sa liste.
    """
    if force or "my_films" not in state:
        _, store = _clients()
        state.my_films = {f["id"]: f for f in store.list_all()}
    return state.my_films


def _stars(note: float) -> str:
    return f"⭐ {note:g}/5".replace(".", ",")


def _close() -> None:
    state.pop("mf_dialog", None)
    state.pop("mf_results", None)


# ---------- Fenêtres : ajouter, modifier, supprimer ----------

def _rating_fields(note: float, comment: str, year: int | None, key: str) -> tuple[float, str, int]:
    this_year = date.today().year
    note = st.slider("Ta note sur 5", 0.0, 5.0, float(note), 0.5, format="%.1f", key=f"{key}-note")
    year = st.number_input("Vu en", min_value=1900, max_value=this_year, value=int(year or this_year),
                           step=1, key=f"{key}-year")
    comment = st.text_area("Ton commentaire", value=comment, height=110, key=f"{key}-comment",
                           placeholder="Ce qui t'a plu ou déplu : le ton, les acteurs, le rythme…")
    return note, comment, int(year)


def _save(**kwargs) -> bool:
    try:
        tmdb, store = _clients()
        stored = save_rating(tmdb, store, Memory(), source="app", **kwargs)
    except Exception as exc:  # message court, sans détail technique
        st.error(f"Enregistrement impossible ({type(exc).__name__}). Réessaie dans un instant.")
        return False
    load_films()[stored["id"]] = stored
    state.mf_toast = f"« {stored['titre']} » enregistré ({stored['note']:g}/5)."
    return True


@st.dialog("Ajouter un film à mes notes", width="medium", on_dismiss=_close)
def add_dialog() -> None:
    films = load_films()
    query = st.text_input("Titre du film", placeholder="Ex. : Le Daim", key="mf-query")
    if st.button("🔎 Chercher dans TMDB", width="stretch") and query.strip():
        try:
            state.mf_results = _clients()[0].search_movies(query.strip(), limit=6)
        except Exception as exc:
            st.error(f"Recherche impossible ({type(exc).__name__}).")
    results = state.get("mf_results")
    if results is None:
        return
    if not results:
        st.info("Aucun film trouvé : essaie le titre original, ou un autre orthographe.")
        return

    def label(m: dict) -> str:
        original = f" · {m['original_title']}" if m.get("original_title") not in (None, m["title"]) else ""
        seen = " — déjà dans tes notes" if f"tmdb-{m['tmdb_id']}" in films else ""
        return f"{m['title']} ({m.get('year') or '?'}){original}{seen}"

    choice = st.radio("Lequel ?", results, format_func=label, key="mf-choice")
    if f"tmdb-{choice['tmdb_id']}" in films:
        st.warning("Ce film est déjà dans tes notes : ferme cette fenêtre et clique sur ✏️ pour le modifier.")
        return
    note, comment, year = _rating_fields(4.0, "", None, "mf-add")
    if st.button("Enregistrer dans mes notes", type="primary", width="stretch"):
        if _save(tmdb_id=choice["tmdb_id"], note=note, commentaire=comment, annee_visionnage=year):
            _close()
            st.rerun()


@st.dialog("Modifier mes notes", width="medium", on_dismiss=_close)
def edit_dialog(film: dict) -> None:
    st.markdown(f"**{escape(film.get('titre', ''))}** "
                f"({film.get('annee_sortie') or '?'}) · {escape(', '.join(film.get('realisation') or []))}")
    note, comment, year = _rating_fields(film.get("note", 3), film.get("commentaire", ""),
                                         film.get("annee_visionnage"), f"mf-edit-{film['id']}")
    st.caption("Le texte de recherche est recalculé : l'agent tiendra compte de ta nouvelle note "
               "et de ton nouveau commentaire.")
    cancel, save = st.columns(2)
    if cancel.button("Annuler", width="stretch"):
        _close()
        st.rerun()
    if save.button("Enregistrer", type="primary", width="stretch"):
        if _save(existing=film, note=note, commentaire=comment, annee_visionnage=year):
            _close()
            st.rerun()


@st.dialog("Supprimer de mes notes ?", on_dismiss=_close)
def delete_dialog(film: dict) -> None:
    st.write(f"« {film.get('titre')} » sera retiré de tes notes : l'agent ne s'en servira plus "
             "pour comprendre tes goûts.")
    cancel, confirm = st.columns(2)
    if cancel.button("Annuler", width="stretch"):
        _close()
        st.rerun()
    if confirm.button("Supprimer", type="primary", width="stretch"):
        try:
            delete_rating(_clients()[1], Memory(), film)
        except Exception as exc:
            st.error(f"Suppression impossible ({type(exc).__name__}).")
            return
        load_films().pop(film["id"], None)
        state.mf_toast = f"« {film.get('titre')} » retiré de tes notes."
        _close()
        st.rerun()


# ---------- La page ----------

def render() -> None:
    st.title("🎞️ Mes films")
    try:
        films = load_films()
    except ConfigError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"Impossible de lire tes notes dans Pinecone ({type(exc).__name__}).")
        return
    if "mf_toast" in state:
        st.toast(state.pop("mf_toast"), icon="✅")

    all_films = list(films.values())
    average = sum(f.get("note", 0) for f in all_films) / len(all_films) if all_films else 0
    average_fr = f"{average:.1f}".replace(".", ",")
    st.caption(f"{len(all_films)} films notés · moyenne {average_fr}/5 · ce sont eux que l'agent "
               "consulte pour comprendre tes goûts.")

    add, refresh, export = st.columns([2, 1, 1])
    if add.button("➕ Ajouter un film", type="primary", width="stretch"):
        state.mf_dialog = ("add", None)
    if refresh.button("🔄 Actualiser", width="stretch", help="Relire tes notes dans Pinecone"):
        load_films(force=True)
        st.rerun()
    export.download_button("⬇️ Exporter (CSV)", to_csv(all_films), file_name="mes_notes.csv",
                           mime="text/csv", width="stretch", help="Pour ton tableur")

    search, note_filter, sort = st.columns([2, 1, 1])
    text = search.text_input("Chercher", placeholder="Titre, réalisateur·rice ou mot du commentaire",
                             label_visibility="collapsed").strip().lower()
    keep = NOTE_FILTERS[note_filter.selectbox("Notes", list(NOTE_FILTERS), label_visibility="collapsed")]
    order = SORTS[sort.selectbox("Tri", list(SORTS), label_visibility="collapsed")]

    def matches(f: dict) -> bool:
        haystack = " ".join([f.get("titre", ""), f.get("commentaire", ""), *(f.get("realisation") or [])]).lower()
        return keep(f.get("note", 0)) and (not text or text in haystack)

    shown = sorted(filter(matches, all_films), key=order)
    if not shown:
        st.info("Aucun film ne correspond.")
    for f in shown:
        with st.container(border=True):
            left, right = st.columns([9, 2], vertical_alignment="center")
            meta = [", ".join((f.get("realisation") or [])[:2]), ", ".join((f.get("genres") or [])[:3]),
                    f"vu en {f['annee_visionnage']}" if f.get("annee_visionnage") else ""]
            left.markdown(
                f'<div class="mf-title">{escape(f.get("titre", ""))} '
                f'<span class="year">{f.get("annee_sortie") or ""}</span> '
                f'<span class="mf-note">{_stars(f.get("note", 0))}</span></div>'
                f'<div class="meta">{escape(" · ".join(m for m in meta if m))}</div>'
                + (f'<div class="mf-comment">« {escape(f["commentaire"])} »</div>' if f.get("commentaire") else ""),
                unsafe_allow_html=True)
            edit, delete = right.columns(2)
            if edit.button("✏️", key=f"mf-edit-btn-{f['id']}", help="Modifier la note ou le commentaire"):
                state.mf_dialog = ("edit", f["id"])
            if delete.button("🗑️", key=f"mf-del-btn-{f['id']}", help="Retirer de mes notes"):
                state.mf_dialog = ("delete", f["id"])

    # La fenêtre demandée reste ouverte jusqu'à validation, annulation ou fermeture.
    kind, film_id = state.get("mf_dialog", (None, None))
    if kind == "add":
        add_dialog()
    elif kind == "edit" and film_id in films:
        edit_dialog(films[film_id])
    elif kind == "delete" and film_id in films:
        delete_dialog(films[film_id])
