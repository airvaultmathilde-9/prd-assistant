# Agent de recommandation de films

Projet d'apprentissage : construire un **vrai agent** (le LLM choisit la suite
d'outils) qui recommande 3 films (choix sûr, découverte, pari) à partir de mes
notes, de mes préférences et de ce qui est disponible en France sur mes
abonnements (Netflix, Canal+).

## Feuille de route

| Phase | Contenu | Concept appris |
|---|---|---|
| **0** | Structure, secrets, vérification des 3 connexions | Hygiène des secrets |
| 1 | Fonctions TMDB : recherche, découverte par critères, détails, plateformes FR | Concevoir un outil |
| 2 | Import de mes notes dans Pinecone + recherche sémantique | RAG |
| 3 | Boucle d'agent avec le Claude Agent SDK, outils branchés, limite de tours | Boucle d'agent |
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

## Règles

1. Aucune clé d'API dans le code, les logs ou l'interface (`.env` est ignoré par git).
2. Aucun film inventé : tout film recommandé vient d'une réponse TMDB de la session.
