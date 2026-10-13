"""Interface web de l'agent : une envie -> 3 cartes de films.

Lancement (depuis film-agent/) :  streamlit run app.py
Une page s'ouvre dans le navigateur (http://localhost:8501).

Streamlit relance ce script de haut en bas à chaque clic : ce qui doit survivre
d'un clic à l'autre (conversation, registre des films) vit dans st.session_state.
"""

from __future__ import annotations

import asyncio
from datetime import date
from html import escape

import streamlit as st

from agent_tools import SessionRegistry
from config import ConfigError, get_settings
from costs import CostLog
from memory import SEEN_STATUSES, STATUSES, Memory
import my_films
from ratings_store import RatingsStore
from seen_films import add_seen_film
from tmdb_client import TMDBClient
from recommend import Answer, Film, recommend

ACCESS_LABELS = {"abonnement": "Inclus", "gratuit": "Gratuit", "location": "Location",
                 "achat": "Achat", "autre_abonnement": "Autre abonnement"}

st.set_page_config(page_title="Ce soir, je regarde…", page_icon="🎬", layout="wide")
st.markdown("""
<style>
  /* Style « moderne » inspiré d'Airbnb : typo Inter, cartes à ombre douce, coins arrondis, accent corail */
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
  html, body, .stApp, .stMarkdown, button, input, textarea { font-family: 'Inter', -apple-system, sans-serif !important; }
  [data-testid="stHeader"] { background: transparent; }
  .block-container { max-width: 1120px; padding-top: 3rem; }
  h1 { font-weight: 800 !important; letter-spacing: -.03em; }
  button { border-radius: 999px !important; font-weight: 600 !important; }
  [data-testid="stMain"] [data-testid="stForm"] { border: none; border-radius: 24px; padding: 1.3rem 1.5rem;
                           box-shadow: 0 6px 28px rgba(0,0,0,.08); }
  [data-testid="stForm"] textarea { border-radius: 16px; font-size: 1.05rem; }
  [class*="st-key-card-"], [class*="st-key-mf-row-"] { background: #fff; border-radius: 20px;
      padding: 1rem 1rem 1.2rem; box-shadow: 0 2px 16px rgba(0,0,0,.08); transition: transform .15s, box-shadow .15s; }
  [class*="st-key-card-"]:hover, [class*="st-key-mf-row-"]:hover { transform: translateY(-2px);
      box-shadow: 0 12px 30px rgba(0,0,0,.12); }
  [class*="st-key-mf-row-"] { border-radius: 16px; padding: .8rem 1.1rem; }
  [data-testid="stSidebar"] { background: #F7F7F7; }
  [data-testid="stSidebar"] [class*="st-key-mem-"] { background: #fff; border-color: transparent !important;
      box-shadow: 0 1px 8px rgba(0,0,0,.05); border-radius: 14px; }
  .role { font-size: .85rem; font-weight: 600; letter-spacing: .02em; opacity: .75; }
  .meta { font-size: .85rem; opacity: .7; margin-bottom: .4rem; }
  .label { font-size: .75rem; font-weight: 700; text-transform: uppercase;
           letter-spacing: .06em; opacity: .55; margin: .8rem 0 .1rem; }
  .watch { font-size: .9rem; margin: .4rem 0; }
  /* « Press Enter to submit form » masquait le texte d'exemple des champs */
  [data-testid="InputInstructions"] { display: none; }
  /* Cartes : badge de rôle coloré et titre bien lisible */
  .badge { display: inline-block; font-size: .8rem; font-weight: 700; padding: .2rem .7rem;
           border-radius: 999px; margin-bottom: .5rem; }
  .badge-choix_sur { background: #ECFDF3; color: #067647; }
  .badge-decouverte { background: #DBEAFE; color: #1E40AF; }
  .badge-pari { background: #F3E8FF; color: #6B21A8; }
  .film-title { font-size: 1.45rem; font-weight: 800; letter-spacing: -.02em; line-height: 1.15; margin: .9rem 0 .3rem; }
  .film-title .year { font-weight: 400; opacity: .5; font-size: 1.2rem; white-space: nowrap; }
  .note { font-size: .9rem; opacity: .75; margin-top: .8rem; }
  /* Page « Mes films » */
  .mf-title { font-size: 1.1rem; font-weight: 700; }
  .mf-title .year { font-weight: 400; opacity: .5; font-size: .95rem; }
  .mf-note { font-weight: 600; font-size: .9rem; margin-left: .4rem; }
  .mf-comment { font-style: italic; font-size: .92rem; opacity: .85; margin-top: .2rem; }
  /* Panneau « Ma mémoire » */
  .mem-title { font-size: 1rem; font-weight: 700; margin-bottom: .3rem; }
  .mem-title .count { font-size: .75rem; font-weight: 700; background: #FFF0F3; color: #E31C5F;
                      border-radius: 999px; padding: .05rem .5rem; margin-left: .3rem; vertical-align: middle; }
  .mem-item { font-size: .92rem; line-height: 1.35; }
  .mem-title .budget { font-weight: 600; opacity: .7; margin-left: .3rem; font-size: .9rem; }
  /* Une couleur par section du panneau mémoire (bordure gauche) */
  [class*="st-key-mem-"] { border-left-width: 5px !important; }
  .st-key-mem-budget { border-left-color: #64748B !important; }
  .st-key-mem-plus_tard { border-left-color: #EA580C !important; }
  .st-key-mem-prefs { border-left-color: #7C3AED !important; }
  .st-key-mem-vu_aime { border-left-color: #16A34A !important; }
  .st-key-mem-vu_pas_aime { border-left-color: #94A3B8 !important; }
  .st-key-mem-pas_envie { border-left-color: #DC2626 !important; }
  /* Affiches : hauteur fixe, recadrées, pour que les infos restent visibles */
  [data-testid="stImage"] img { height: 320px; object-fit: cover; border-radius: 14px; }
</style>
""", unsafe_allow_html=True)

# ---------- État conservé entre deux clics ----------
state = st.session_state
state.setdefault("registry", SessionRegistry())
state.setdefault("session_id", None)   # pour continuer la conversation avec l'agent
state.setdefault("answer", None)
state.setdefault("history", [])        # demandes de la conversation en cours
state.setdefault("prompt", "")
if state.pop("clear_prompt", False):
    state.prompt = ""
# Avis à remettre dans les boutons « Ton avis » après la fenêtre « Vu » (un widget ne peut
# être modifié qu'AVANT d'être affiché : on le fait donc ici, en haut du script).
for _key, _value in state.pop("pill_resets", {}).items():
    state[_key] = _value
if "toast" in state:
    st.toast(state.pop("toast"), icon="✅")


def reset() -> None:
    state.registry, state.session_id, state.answer, state.history = SessionRegistry(), None, None, []
    state.prompt = ""


def ask(prompt: str) -> bool:
    """Interroge l'agent. Renvoie True si une réponse a été obtenue."""
    try:
        settings = get_settings()
    except ConfigError as exc:
        st.error(str(exc))
        return False
    with st.status("L'agent cherche…", expanded=True) as status:
        def on_tool(name: str, params: dict) -> None:
            shown = ", ".join(f"{k}={v}" for k, v in params.items())
            status.write(f"🔧 `{name}` {shown[:110]}")

        try:
            answer = asyncio.run(recommend(prompt, settings, state.registry,
                                           state.session_id, on_tool, Memory()))
        except Exception as exc:  # message court : jamais de détail technique sensible
            status.update(label="Erreur", state="error")
            st.error(f"L'agent a rencontré un problème ({type(exc).__name__}).")
            return False
        status.update(label="C'est trouvé !" if answer.films else "Réponse de l'agent",
                      state="complete", expanded=False)
    state.history.append(prompt)
    state.answer, state.session_id = answer, answer.session_id
    state.pop("my_films", None)  # l'agent a pu ajouter un film vu : « Mes films » relira la liste
    # Si l'agent pose une question, on vide le champ pour qu'elle y réponde.
    # (Impossible de le faire ici : le champ est déjà affiché. On le fait au prochain affichage.)
    state.clear_prompt = answer.kind == "question"
    return True


def save_feedback(tmdb_id: int, title: str, key: str) -> None:
    memory, status = Memory(), state[key]
    if status in SEEN_STATUSES:
        # « Vu » : on ouvre la fenêtre pour compléter la fiche. Rien n'est enregistré avant
        # validation : en attendant, le bouton revient à l'avis actuel.
        state.seen_dialog = {"tmdb_id": tmdb_id, "title": title, "status": status, "key": key}
        state[key] = memory.status_of(tmdb_id)
        return
    if status:
        memory.set_feedback(tmdb_id, title, status)
    else:  # cliquer à nouveau sur l'avis choisi l'annule
        memory.clear_feedback(tmdb_id)


SIDEBAR_ORDER = ["plus_tard", "vu_aime", "vu_pas_aime", "pas_envie"]  # « Plus tard » d'abord : la plus utile
VISIBLE_ITEMS = 5  # au-delà, le reste de la liste est replié


def memory_row(text: str, key: str, on_delete, help_text: str) -> None:
    left, right = st.columns([6, 1], vertical_alignment="center")
    left.markdown(f'<div class="mem-item">{escape(text)}</div>', unsafe_allow_html=True)
    right.button("🗑️", key=key, help=help_text, type="tertiary", on_click=on_delete)


def memory_section(key: str, title: str, rows: list[tuple[str, str, object, str]]) -> None:
    """Une section colorée du panneau (la couleur vient du CSS « st-key-mem-… »)."""
    with st.container(key=f"mem-{key}", border=True):
        st.markdown(f'<div class="mem-title">{title} <span class="count">{len(rows)}</span></div>',
                    unsafe_allow_html=True)
        for row in rows[:VISIBLE_ITEMS]:
            memory_row(*row)
        if len(rows) > VISIBLE_ITEMS:
            with st.expander(f"Voir les {len(rows) - VISIBLE_ITEMS} autres"):
                for row in rows[VISIBLE_ITEMS:]:
                    memory_row(*row)


def render_budget(settings) -> None:
    spent, limit = CostLog().today(), settings.daily_budget_usd
    with st.container(key="mem-budget", border=True):
        st.markdown(f'<div class="mem-title">💶 Aujourd\'hui <span class="budget">'
                    f'{spent:.2f} $ / {limit:.2f} $</span></div>', unsafe_allow_html=True)
        st.progress(min(spent / limit, 1.0) if limit else 1.0)
        st.caption(f"Max {settings.max_turns} tours et {settings.max_budget_usd:.2f} $ par recherche. "
                   "Réglable dans .env.")


def render_memory_sidebar() -> None:
    memory = Memory()
    with st.sidebar:
        st.header("🧠 Ma mémoire")
        try:
            render_budget(get_settings())
        except ConfigError:
            pass  # l'erreur de configuration s'affiche déjà au moment de chercher

        later = memory.films_with("plus_tard")
        if later:
            memory_section("plus_tard", STATUSES["plus_tard"],
                           [(t, f"fb-del-{i}", lambda i=i: Memory().clear_feedback(i), "Retirer de la liste")
                            for i, t in later])

        with st.container(key="mem-prefs", border=True):
            st.markdown(f'<div class="mem-title">⭐ Préférences '
                        f'<span class="count">{len(memory.preferences)}</span></div>', unsafe_allow_html=True)
            for pref in memory.preferences:
                memory_row(pref["texte"], f"pref-{pref['id']}",
                           lambda i=pref["id"]: Memory().remove_preference(i), "Oublier cette préférence")
            with st.form("nouvelle-preference", clear_on_submit=True, border=False):
                new_pref = st.text_input("Ajouter une préférence", placeholder="Ex. : je préfère la VO sous-titrée",
                                         label_visibility="collapsed")
                if st.form_submit_button("Ajouter", width="stretch") and new_pref.strip():
                    memory.add_preference(new_pref)
                    st.rerun()

        for status in SIDEBAR_ORDER[1:]:
            films = memory.films_with(status)
            if films:
                memory_section(status, STATUSES[status],
                               [(t, f"fb-del-{i}", lambda i=i: Memory().clear_feedback(i), "Retirer de la liste")
                                for i, t in films])
        st.caption("L'agent relit cette mémoire à chaque recherche. Rien ne s'efface tout seul.")


def close_seen_dialog() -> None:
    state.pop("seen_dialog", None)


# on_dismiss : fermer avec la croix (ou Échap) = annuler, rien n'est enregistré.
@st.dialog("Ajouter à mes notes", width="medium", on_dismiss=close_seen_dialog)
def seen_dialog(info: dict) -> None:
    """Fiche complète d'un film vu : elle rejoint mes notes Pinecone (le RAG apprend)."""
    liked = info["status"] == "vu_aime"
    this_year = date.today().year
    st.markdown(f"**{escape(info['title'])}** · {STATUSES[info['status']]}")
    note = st.slider("Ta note sur 5", 0.0, 5.0, 4.0 if liked else 2.0, 0.5, format="%.1f")
    year = st.number_input("Vu en", min_value=1900, max_value=this_year, value=this_year, step=1)
    comment = st.text_area("Ton commentaire",
                           placeholder="Ce qui t'a plu ou déplu : le ton, les acteurs, le rythme…",
                           height=110)
    st.caption("Ces informations rejoignent tes notes : l'agent s'en servira pour comprendre tes goûts, "
               "comme pour les films de ton CSV.")
    cancel, save = st.columns(2)
    if cancel.button("Annuler", width="stretch"):
        close_seen_dialog()
        st.rerun()
    if save.button("Enregistrer dans mes notes", type="primary", width="stretch"):
        try:
            settings = get_settings()
            add_seen_film(TMDBClient(settings.tmdb_api_key),
                          RatingsStore(settings.pinecone_api_key, settings.pinecone_index),
                          Memory(), info["tmdb_id"], note, comment, int(year), info["status"], source="app")
        except Exception as exc:  # message court, sans détail technique
            st.error(f"Enregistrement impossible ({type(exc).__name__}). Réessaie dans un instant.")
            return
        close_seen_dialog()
        state.pop("my_films", None)  # la page « Mes films » relira la liste à jour
        state.pill_resets = {info["key"]: info["status"]}
        state.toast = f"« {info['title']} » ajouté à tes notes ({note:g}/5)."
        st.rerun()


def render_card(film: Film) -> None:
    d, watch = film.details, film.watch
    with st.container(key=f"card-{film.tmdb_id}"):
        st.markdown(f'<span class="badge badge-{film.role}">{film.role_label}</span>',
                    unsafe_allow_html=True)
        if d.get("poster_url"):
            st.image(d["poster_url"], width="stretch")
        # escape : un titre est du texte venu de TMDB, on ne l'injecte jamais tel quel dans du HTML.
        year = f' <span class="year">{d["year"]}</span>' if d.get("year") else ""
        st.markdown(f'<div class="film-title">{escape(d.get("title") or "")}{year}</div>',
                    unsafe_allow_html=True)
        meta = [", ".join(d.get("directors", [])[:2]), film.runtime_label, film.language_label]
        st.markdown(f'<div class="meta">{" · ".join(m for m in meta if m)}</div>', unsafe_allow_html=True)

        if film.rating_label:
            st.markdown(f'<div class="meta">{film.rating_label} <span title="Note du public sur TMDB">'
                        f'(public)</span></div>', unsafe_allow_html=True)

        options = watch.get("options", [])
        if options:
            best = options[0]
            st.markdown(f'<div class="watch">📺 <b>{best["platform"]}</b> · '
                        f'{ACCESS_LABELS.get(best["access"], best["access"])}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<div class="watch">📺 Pas disponible à la maison en France pour l\'instant</div>',
                        unsafe_allow_html=True)
        # Deux boutons l'un sous l'autre (côte à côte, leurs textes étaient coupés).
        if options:
            st.link_button(f"▶️ Regarder sur {best['platform']}", best["link"], width="stretch")
        if film.trailer:
            st.link_button("🎬 Bande-annonce", film.trailer["url"], width="stretch",
                                    help="Sur YouTube" + (" (en anglais)" if film.trailer["language"] != "fr" else ""))
        if options:
            others = [f"{o['platform']} ({ACCESS_LABELS.get(o['access'], o['access']).lower()})"
                      for o in options[1:4]]
            if others:
                st.caption("Aussi : " + ", ".join(others))

        st.markdown('<div class="label">Pourquoi</div>', unsafe_allow_html=True)
        st.write(film.why)
        st.markdown('<div class="label">L\'ambiance</div>', unsafe_allow_html=True)
        st.write(film.vibe)

        # Retour sur le film : enregistré dans la mémoire, relu par l'agent à la prochaine demande.
        key = f"avis-{film.tmdb_id}"
        st.pills("Ton avis", list(STATUSES), format_func=STATUSES.get, selection_mode="single",
                 default=Memory().status_of(film.tmdb_id), key=key,
                 on_change=save_feedback, args=(film.tmdb_id, d.get("title") or "", key))


def render_answer(answer: Answer) -> None:
    if answer.kind == "error":
        st.error(answer.message)
        return
    if answer.kind == "question":
        st.info(f"**L'agent te demande :** {answer.message}\n\nRéponds dans la zone ci-dessus.")
        return
    if answer.rejected:
        st.caption(f"{len(answer.rejected)} proposition(s) écartée(s) car non vérifiée(s) dans TMDB.")
    if not answer.films:
        st.warning("Aucun film vérifié à proposer. Essaie une autre formulation.")
        return
    for column, film in zip(st.columns(len(answer.films)), answer.films):
        with column:
            render_card(film)
    if answer.message and len(answer.films) < 3:  # explique discrètement pourquoi moins de 3 films
        st.markdown(f'<div class="note">ℹ️ {escape(answer.message)}</div>', unsafe_allow_html=True)
    cost = f" · {answer.cost_usd:.2f} $" if answer.cost_usd is not None else ""
    st.caption(f"{answer.turns} tours{cost}")


# ---------- Les pages ----------

def page_recommend() -> None:
    render_memory_sidebar()
    st.title("🎬 Ce soir, je regarde…")
    st.caption("Dis-moi ton envie : je cherche dans tes notes et dans le catalogue, "
               "puis je te propose un choix sûr, une découverte et un pari.")

    if state.history:
        st.caption("Conversation : " + " → ".join(f"« {h} »" for h in state.history))

    with st.form("demande", clear_on_submit=False):
        label = "Ta réponse" if state.answer and state.answer.kind == "question" else "De quoi as-tu envie ?"
        prompt = st.text_area(label, key="prompt", height=90,
                              placeholder="Ex. : un thriller coréen pas trop violent, à regarder ce soir")
        left, right = st.columns([3, 1])
        submitted = left.form_submit_button("Trouver 3 films", type="primary", width="stretch")
        right.form_submit_button("Nouvelle recherche", width="stretch", on_click=reset)

    if submitted and prompt.strip() and ask(prompt.strip()):
        st.rerun()  # réaffiche la page avec la réponse (et le bon libellé du champ)

    if state.answer:
        render_answer(state.answer)
    if "seen_dialog" in state:  # un « Vu » a été cliqué : la fenêtre reste ouverte jusqu'à validation ou annulation
        seen_dialog(state.seen_dialog)

    st.divider()
    st.caption("Données films : TMDB (ce produit utilise l'API TMDB sans être approuvé ni certifié par TMDB). "
               "Disponibilités : JustWatch.")


# Deux pages, avec un menu en haut du panneau de gauche.
st.navigation([
    st.Page(page_recommend, title="Ce soir, je regarde…", icon="🎬", default=True),
    st.Page(my_films.render, title="Mes films", icon="🎞️", url_path="mes-films"),
]).run()
