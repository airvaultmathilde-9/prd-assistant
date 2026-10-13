#!/bin/bash
# ------------------------------------------------------------------
#  Double-clique sur ce fichier pour lancer l'agent films.
#  (Sur Mac, un fichier .command s'ouvre dans le Terminal et
#   exécute les commandes ci-dessous, sans rien avoir à taper.)
#
#  Pour l'arrêter : ferme la fenêtre du Terminal (ou control + C).
# ------------------------------------------------------------------

BRANCHE="claude/inspiring-knuth-vnwryy"   # la version officielle (branche principale)
URL="http://localhost:8501"

# 1. Aller dans le projet. Le fichier est dans film-agent/ : le projet est le dossier parent.
#    (Si le fichier a été COPIÉ ailleurs, on prend l'emplacement habituel.)
PROJET="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)"
if [ ! -d "$PROJET/film-agent" ]; then
    PROJET="$HOME/Documents/prd-assistant"
fi
cd "$PROJET" || { echo "❌ Projet introuvable dans $PROJET"; read -r -p "Entrée pour fermer…"; exit 1; }

echo "🎬 Agent films"
echo

# 2. Déjà lancé ? Alors on ouvre juste la page.
if lsof -nP -iTCP:8501 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "L'agent tourne déjà : j'ouvre la page."
    open "$URL"
    exit 0
fi

# 3. Récupérer la dernière version validée sur GitHub (git checkout + git pull).
echo "🔄 Mise à jour du code…"
if git checkout -q "$BRANCHE" && git pull -q; then
    echo "   ✅ $(git log --oneline -1)"
else
    echo "   ⚠️  Mise à jour impossible (pas d'internet ?). Je lance la version déjà présente."
fi

# 4. Activer l'environnement Python du projet.
if [ ! -f .venv/bin/activate ]; then
    echo "❌ Environnement .venv introuvable. Voir le README (installation)."
    read -r -p "Entrée pour fermer…"
    exit 1
fi
source .venv/bin/activate

# 5. Réinstaller les bibliothèques SEULEMENT si la liste a changé depuis la dernière fois.
EMPREINTE_ACTUELLE="$(shasum film-agent/requirements.txt | cut -d' ' -f1)"
EMPREINTE_FICHIER=".venv/.requirements-empreinte"
if [ "$EMPREINTE_ACTUELLE" != "$(cat "$EMPREINTE_FICHIER" 2>/dev/null)" ]; then
    echo "📦 Nouvelles bibliothèques à installer (une minute)…"
    if pip install -q -r film-agent/requirements.txt; then
        echo "$EMPREINTE_ACTUELLE" > "$EMPREINTE_FICHIER"
    else
        echo "   ⚠️  Installation incomplète : je tente de lancer quand même."
    fi
fi

# 6. Lancer l'interface. Streamlit ouvre le navigateur tout seul.
echo
echo "🚀 Lancement : la page s'ouvre dans ton navigateur ($URL)."
echo "   Laisse cette fenêtre ouverte pendant que tu utilises l'agent ; ferme-la pour l'arrêter."
echo
cd film-agent
streamlit run app.py
