"""Interface web de l'agent : une envie -> 3 cartes de films.

Lancement (depuis film-agent/) :  streamlit run app.py
Une page s'ouvre dans le navigateur (http://localhost:8501).

Streamlit relance ce script de haut en bas à chaque clic : ce qui doit survivre
d'un clic à l'autre (conversation, registre des films) vit dans st.session_state.
"""

from __future__ import annotations

import asyncio

import streamlit as st

from agent_tools import SessionRegistry
from config import ConfigError, get_settings
from memory import STATUSES, Memory
from recommend import Answer, Film, recommend

EXAMPLES = [
    "Un film avec Adèle Exarchopoulos en moins de deux heures",
    "Un drame sur le thème de la Seconde Guerre mondiale",
    "Un film de Dupieux que je n'ai pas encore vu",
]
ACCESS_LABELS = {"abonnement": "Inclus", "gratuit": "Gratuit", "location": "Location",
                 "achat": "Achat", "autre_abonnement": "Autre abonnement"}

st.set_page_config(page_title="Ce soir, je regarde…", page_icon="🎬", layout="wide")
st.markdown("""
<style>
  .block-container { max-width: 1150px; padding-top: 2.5rem; }
  .role { font-size: .85rem; font-weight: 600; letter-spacing: .02em; opacity: .75; }
  .meta { font-size: .85rem; opacity: .7; margin-top: -.6rem; }
  .label { font-size: .75rem; font-weight: 700; text-transform: uppercase;
           letter-spacing: .06em; opacity: .55; margin: .8rem 0 .1rem; }
  .watch { font-size: .9rem; margin: .4rem 0; }
  /* Boutons d'exemples : texte complet (sur plusieurs lignes), bien visibles */
  .st-key-examples button { height: auto; min-height: 4rem; padding: .6rem 1rem;
      border: 1.5px solid #C2410C; background: #FFF7ED; color: #9A3412; }
  .st-key-examples button:hover { background: #FFEDD5; border-color: #9A3412; color: #7C2D12; }
  .st-key-examples button p { white-space: normal !important; overflow: visible !important;
      text-overflow: clip !important; font-weight: 600; line-height: 1.3; }
  /* Affiches : hauteur fixe, recadrées, pour que les infos restent visibles */
  [data-testid="stImage"] img { height: 300px; object-fit: cover; border-radius: 8px; }
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
    # Si l'agent pose une question, on vide le champ pour qu'elle y réponde.
    # (Impossible de le faire ici : le champ est déjà affiché. On le fait au prochain affichage.)
    state.clear_prompt = answer.kind == "question"
    return True


def save_feedback(tmdb_id: int, title: str, key: str) -> None:
    memory, status = Memory(), state[key]
    if status:
        memory.set_feedback(tmdb_id, title, status)
    else:  # cliquer à nouveau sur l'avis choisi l'annule
        memory.clear_feedback(tmdb_id)


def render_memory_sidebar() -> None:
    memory = Memory()
    with st.sidebar:
        st.header("🧠 Ma mémoire")
        st.caption("L'agent relit tout ceci à chaque recherche. Tu peux aussi lui dire "
                   "« je préfère la VO » dans une demande : il le notera ici.")
        st.markdown('<div class="label">Préférences</div>', unsafe_allow_html=True)
        for pref in memory.preferences:
            left, right = st.columns([5, 1])
            left.write(pref["texte"])
            right.button("🗑️", key=f"pref-{pref['id']}", help="Oublier",
                         on_click=lambda i=pref["id"]: Memory().remove_preference(i))
        with st.form("nouvelle-preference", clear_on_submit=True, border=False):
            new_pref = st.text_input("Ajouter une préférence", placeholder="Ex. : je préfère la VO sous-titrée",
                                     label_visibility="collapsed")
            if st.form_submit_button("Ajouter") and new_pref.strip():
                memory.add_preference(new_pref)
                st.rerun()
        for status, label in STATUSES.items():
            films = memory.films_with(status)
            if films:
                st.markdown(f'<div class="label">{label}</div>', unsafe_allow_html=True)
                for tmdb_id, title in films:
                    left, right = st.columns([5, 1])
                    left.write(title)
                    right.button("🗑️", key=f"fb-del-{tmdb_id}", help="Retirer",
                                 on_click=lambda i=tmdb_id: Memory().clear_feedback(i))


def render_card(film: Film) -> None:
    d, watch = film.details, film.watch
    with st.container(border=True):
        st.markdown(f'<div class="role">{film.role_label}</div>', unsafe_allow_html=True)
        if d.get("poster_url"):
            st.image(d["poster_url"], use_container_width=True)
        st.subheader(f"{d.get('title')} ({d.get('year') or '?'})")
        meta = [", ".join(d.get("directors", [])[:2]),
                f"{d['runtime_min']} min" if d.get("runtime_min") else "",
                film.language_label]
        st.markdown(f'<div class="meta">{" · ".join(m for m in meta if m)}</div>', unsafe_allow_html=True)

        options = watch.get("options", [])
        if options:
            best = options[0]
            st.markdown(f'<div class="watch">📺 <b>{best["platform"]}</b> · '
                        f'{ACCESS_LABELS.get(best["access"], best["access"])}</div>',
                        unsafe_allow_html=True)
            st.link_button(f"Regarder sur {best['platform']}", best["link"], use_container_width=True)
            others = [f"{o['platform']} ({ACCESS_LABELS.get(o['access'], o['access']).lower()})"
                      for o in options[1:4]]
            if others:
                st.caption("Aussi : " + ", ".join(others))
        else:
            st.markdown('<div class="watch">📺 Pas disponible à la maison en France pour l\'instant</div>',
                        unsafe_allow_html=True)

        st.markdown('<div class="label">Pourquoi toi</div>', unsafe_allow_html=True)
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
    if answer.message:
        st.markdown(f"#### {answer.message}")
    if answer.rejected:
        st.caption(f"{len(answer.rejected)} proposition(s) écartée(s) car non vérifiée(s) dans TMDB.")
    if not answer.films:
        st.warning("Aucun film vérifié à proposer. Essaie une autre formulation.")
        return
    for column, film in zip(st.columns(len(answer.films)), answer.films):
        with column:
            render_card(film)
    cost = f" · {answer.cost_usd:.2f} $" if answer.cost_usd is not None else ""
    st.caption(f"{answer.turns} tours{cost}")


# ---------- Page ----------
render_memory_sidebar()
st.title("🎬 Ce soir, je regarde…")
st.caption("Dis-moi ton envie : je cherche dans tes notes et dans le catalogue, "
           "puis je te propose un choix sûr, une découverte et un pari.")

if state.history:
    st.caption("Conversation : " + " → ".join(f"« {h} »" for h in state.history))

with st.container(key="examples"):  # key -> classe CSS « st-key-examples » pour le style
    st.markdown('<div class="label">Idées pour commencer</div>', unsafe_allow_html=True)
    example_columns = st.columns(len(EXAMPLES))
for column, example in zip(example_columns, EXAMPLES):
    # on_click : s'exécute AVANT le réaffichage, seul moment où l'on peut changer le champ texte.
    column.button(example, use_container_width=True, on_click=state.update, args=({"prompt": example},))

with st.form("demande", clear_on_submit=False):
    label = "Ta réponse" if state.answer and state.answer.kind == "question" else "De quoi as-tu envie ?"
    prompt = st.text_area(label, key="prompt", height=90,
                          placeholder="Ex. : un thriller coréen pas trop violent, à regarder ce soir")
    left, right = st.columns([3, 1])
    submitted = left.form_submit_button("Trouver 3 films", type="primary", use_container_width=True)
    right.form_submit_button("Nouvelle recherche", use_container_width=True, on_click=reset)

if submitted and prompt.strip() and ask(prompt.strip()):
    st.rerun()  # réaffiche la page avec la réponse (et le bon libellé du champ)

if state.answer:
    render_answer(state.answer)

st.divider()
st.caption("Données films : TMDB (ce produit utilise l'API TMDB sans être approuvé ni certifié par TMDB). "
           "Disponibilités : JustWatch.")
