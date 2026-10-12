# Agent de recommandation de films

Projet d'apprentissage : construire un **vrai agent** (le LLM choisit la suite
d'outils) qui recommande 3 films (choix sûr, découverte, pari) à partir de mes
notes, de mes préférences et de ce qui est disponible en France sur mes
abonnements (Netflix, Canal+).

## Feuille de route

| Phase | Contenu | Concept appris |
|---|---|---|
| 0 ✅ | Structure, secrets, vérification des 3 connexions | Hygiène des secrets |
| 1 ✅ | Fonctions TMDB : recherche, découverte par critères, détails, plateformes FR | Concevoir un outil |
| 2 ✅ | Import de mes notes dans Pinecone + recherche sémantique | RAG |
| **3** | Boucle d'agent avec le Claude Agent SDK, outils branchés, limite de tours | Boucle d'agent |
| 4 | Mémoire des préférences et des retours, skill « recommandation » | Mémoire, skills |
| 5 | Hooks : aucun film hors TMDB, pas de spoiler, pas de clé dans les logs | Garde-fous |
| 6 | Interface Streamlit avec cartes de films | Produit |
| 7 | Jeu de cas de test et notation automatique | Evals |

## Installation

```bash
# depuis la racine du dépôt, avec ton .venv activé
pip install -r film-agent/requirements.txt
cp film-agent/.env.example film-agent/.env   # puis remplis les clés
```

## Phase 0 : vérifier les connexions

```bash
cd film-agent
python scripts/check_setup.py
```

Résultat attendu : trois lignes ✅ (Anthropic, Pinecone, TMDB).

## Phase 1 : les outils TMDB

`tmdb_client.py` contient les fonctions que l'agent appellera :

| Fonction | Rôle |
|---|---|
| `search_movies` | chercher un film par son titre |
| `discover_movies` | trouver des films par critères (genres, années, note, langue, pays, personnes, thèmes, durée, sur mes abonnements) |
| `get_movie_details` | fiche complète : réalisation, casting, durée, langues, mots-clés |
| `get_watch_providers` | où le voir **chez moi** en France, avec un lien par option, dans l'ordre : abonnement (Netflix, Canal+) → gratuit (Arte, france.tv…) → location → achat. Pas de séances de cinéma |
| `get_person_filmography` | films réalisés par quelqu'un, ou films où quelqu'un a un rôle principal |
| `search_person` / `search_keyword` | traduire « Sciamma » ou « voyage dans le temps » en identifiants pour `discover_movies` |

```bash
cd film-agent
python -m pytest -q tests            # tests sans réseau (TMDB simulé)
python scripts/demo_tmdb.py          # appels réels à TMDB
python scripts/demo_tmdb.py "Drive"  # avec un titre de ton choix
```

Données de disponibilité fournies par JustWatch (via TMDB).

## Phase 2 : mes notes dans Pinecone (RAG)

1. Dépose ton CSV dans `film-agent/data/` (ignoré par git). Colonnes attendues :
   `titre`, `note_sur_5` (obligatoires), `annee_sortie`, `annee_visionnage`, `commentaire`.
   Séparateur : tabulation, point-virgule ou virgule.
2. Lance l'import :

```bash
cd film-agent
python scripts/import_notes.py data/mes_notes.csv --dry-run   # essai, rien n'est envoyé
python scripts/import_notes.py data/mes_notes.csv             # import réel
python scripts/demo_rag.py                                    # requêtes d'exemple
python scripts/demo_rag.py "un film qui fait réfléchir" --min-note 4
```

Chaque film est associé à un identifiant TMDB (✅ sûr, 🟡 probable, ⚠️ à vérifier,
❌ introuvable). Les associations sont enregistrées dans `data/correspondances_tmdb.json` :
tu peux y corriger un `tmdb_id` à la main, puis relancer l'import (sans doublon).

| Module | Rôle |
|---|---|
| `ratings_csv.py` | lit le CSV, retrouve chaque film dans TMDB, écrit le texte à vectoriser |
| `ratings_store.py` | Pinecone : création de l'index, envoi, `search` (recherche sémantique) et `already_seen` |

## Phase 3 : l'agent

```bash
cd film-agent
python agent.py               # conversation dans le Terminal (« quit » pour sortir)
python agent.py --trace-full  # avec les paramètres complets de chaque appel d'outil
```

| Fichier | Rôle |
|---|---|
| `prompts/system_prompt.md` | les instructions de l'agent : qui il est, comment travailler, règles, format |
| `agent_tools.py` | les 9 outils (TMDB + mes notes), avec leurs descriptions pour Claude |
| `agent.py` | assemble l'agent (Claude Agent SDK), fixe les limites, affiche la trace |

Limites : 25 tours et 1 $ maximum par question ; aucun outil intégré de Claude Code
(pas de terminal, de fichiers ni de web) : l'agent ne peut utiliser que nos 9 outils.

## Règles

1. Aucune clé d'API dans le code, les logs ou l'interface (`.env` est ignoré par git).
2. Aucun film inventé : tout film recommandé vient d'une réponse TMDB de la session.
