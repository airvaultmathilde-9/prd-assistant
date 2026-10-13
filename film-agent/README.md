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
| 3 ✅ | Boucle d'agent avec le Claude Agent SDK, outils branchés, limite de tours | Boucle d'agent |
| **4** | Mémoire des préférences et des retours, skill « recommandation » | Mémoire, skills |
| 5 | Hooks : aucun film hors TMDB, pas de spoiler, pas de clé dans les logs | Garde-fous |
| 6 (en avance) | Interface Streamlit avec cartes de films | Produit |
| 7 | Jeu de cas de test et notation automatique | Evals |

## Lancer l'agent (au quotidien)

Double-clique sur **`Lancer agent films.command`** (dans `film-agent/`, depuis le Finder).
Il met le code à jour depuis GitHub, réinstalle les bibliothèques si la liste a changé,
lance l'interface et ouvre le navigateur. Si l'agent tourne déjà, il ouvre simplement la page.
Pour l'arrêter : ferme la fenêtre du Terminal.

Astuce : clic droit sur le fichier → **Créer un alias**, puis glisse l'alias sur le Bureau ou dans le Dock.

## Page « Mes films » : mes notes, gérées dans l'app

Menu à gauche → **🎞️ Mes films** : tous les films de ta base Pinecone, avec recherche, filtre par note et tri.

- **➕ Ajouter** : tu tapes un titre, tu choisis le bon film dans TMDB, puis tu donnes ta **note**, ton
  **commentaire** et l'**année de visionnage**. Le reste (année de sortie, réalisation, genres, casting,
  résumé) vient automatiquement de TMDB.
- **✏️ Modifier** : note, commentaire, année de visionnage. Le texte de recherche est recalculé, donc
  l'agent tient compte de tes modifications.
- **🗑️ Supprimer**, et **⬇️ Exporter** en CSV pour ton tableur.
- Aucun appel à Claude : c'est gratuit (TMDB et Pinecone seulement).

**L'app fait foi** : un film ajouté ou modifié ici (ou par l'agent) n'est plus jamais écrasé ni supprimé
par `scripts/import_notes.py`. L'import du CSV ne sert plus qu'à ajouter des films en masse.

## Garde-fous de coût

Seule l'API Anthropic est payante (TMDB et Pinecone sont gratuits). Une recherche coûte d'autant plus
qu'elle fait de **tours** : à chaque tour, tout le contexte (instructions, mémoire, outils, résultats déjà
obtenus) est relu par Claude. Réglages dans `.env` (voir `.env.example`) :

| Variable | Défaut | Effet |
|---|---|---|
| `AGENT_MAX_TURNS` | 12 | tours maximum par recherche ; l'agent connaît ce budget et conclut avant |
| `AGENT_MAX_BUDGET_USD` | 0.25 | coût maximum d'une recherche |
| `AGENT_DAILY_BUDGET_USD` | 1.00 | coût maximum par jour : au-delà, plus aucune recherche jusqu'au lendemain |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | `claude-haiku-5-5` coûte nettement moins cher (choix un peu moins fins) |

Le total du jour est affiché en haut du panneau « Ma mémoire » (compteur dans `data/memory/couts.json`).
Conseil : fixe aussi une limite mensuelle sur console.anthropic.com.

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

## Phase 4 : mémoire et skill

| Fichier | Rôle |
|---|---|
| `memory.py` | la mémoire : préférences durables + retours (vu et aimé / pas envie / plus tard), dans `data/memory/memoire.json` (privé, ignoré par git) |
| `.claude/skills/selection-3-films/SKILL.md` | la skill : méthode pour composer les 3 films et écrire sans spoiler, chargée par l'agent quand il en a besoin |

- La mémoire est **ajoutée au prompt** à chaque demande : l'agent la connaît sans la chercher.
- L'agent la **complète lui-même** (`remember_preference`, `record_feedback`) quand tu exprimes
  une préférence durable (« je préfère la VO ») ; une envie du moment (« ce soir je veux rire ») n'est pas mémorisée.
- Dans l'interface : boutons **Ton avis** sous chaque carte, et panneau **Ma mémoire** à gauche.

### « Je l'ai déjà vu » : l'agent apprend

Dis-le à l'agent (« j'ai déjà vu Le Daim, 4/5, très drôle ») ou clique **✅ Vu et aimé** / **👎 Vu et pas aimé**
sous une carte : une fenêtre s'ouvre pour compléter la fiche (note, année de visionnage, commentaire).
Le film est alors ajouté à tes notes **dans Pinecone** (`seen_films.py`), avec les mêmes informations qu'une ligne
de ton CSV, enrichies par TMDB (réalisation, genres, casting, résumé). Rien n'est enregistré si tu annules.
Les recherches suivantes s'en servent, comme pour les films de ton CSV.

- Même identifiant que l'import (`tmdb-12345`) : pas de doublon ; si tu l'ajoutes plus tard au CSV, ta version l'emporte.
- Marqués `source: agent` : **l'import ne les supprime jamais**.
- Journal dans `data/ajouts_agent.csv` (mêmes colonnes que ton CSV) : à recopier dans ton tableur si tu veux.

## Interface web (Streamlit)

⚠️ Streamlit demande **Python 3.13** : sa dépendance `pyarrow` n'existe pas encore pour 3.15
dans une version compatible.

```bash
cd film-agent
streamlit run app.py      # ouvre http://localhost:8501
```

| Fichier | Rôle |
|---|---|
| `app.py` | la page : une envie → 3 cartes (affiche, durée, où regarder, pourquoi, ambiance) |
| `recommend.py` | lance l'agent avec une réponse **structurée** (JSON), écarte tout film non vérifié dans TMDB, relit les faits dans TMDB |
| `.streamlit/config.toml` | thème de la page |

## Règles

1. Aucune clé d'API dans le code, les logs ou l'interface (`.env` est ignoré par git).
2. Aucun film inventé : tout film recommandé vient d'une réponse TMDB de la session.
