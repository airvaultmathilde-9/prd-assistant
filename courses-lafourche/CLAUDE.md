# Courses La Fourche

Outil personnel en ligne de commande qui transforme les recettes de la semaine
en liste de courses à commander sur La Fourche (épicerie bio en ligne).

## Ce que fait l'outil

1. Lit toutes les recettes d'un dossier de semaine (`recettes/AAAA-Sxx/*.txt`).
2. Extrait les lignes d'ingrédients de chaque recette (texte libre copié du web).
3. Analyse chaque ligne : quantité, unité, ingrédient.
4. Normalise le nom de l'ingrédient (minuscules, singulier, alias).
5. Fusionne les doublons et additionne les quantités compatibles.
6. Associe chaque ingrédient à un produit du catalogue perso (`donnees/catalogue.csv`).
7. Calcule le nombre de produits à commander quand le format le permet.
8. Écrit la liste de courses en Markdown dans `listes/AAAA-Sxx.md`.

Commande prévue :

```
python3 courses.py recettes/2026-S41
```

## Règles absolues

- **Aucun accès réseau au site La Fourche.** Pas de scraping, pas de requête
  HTTP, pas d'appel à une API non officielle : leur `robots.txt` l'interdit.
  L'outil ne fait que *construire* des URL (liens produit du catalogue, liens de
  recherche) que l'utilisatrice ouvre elle-même dans son navigateur.
  Cela vaut aussi pour Claude pendant le développement : ne pas utiliser
  WebFetch, curl ou un navigateur sur lafourche.fr pour remplir le catalogue
  ou vérifier des produits.
- **Tout en français** : messages de la CLI, contenu des fichiers générés,
  commentaires, docstrings, noms de fichiers de données. Les identifiants de
  code (variables, fonctions) peuvent rester en français sans accents.
- **Ne jamais deviner silencieusement.** Une ligne non comprise, un ingrédient
  absent du catalogue ou des unités impossibles à additionner sont *signalés*
  dans la liste, jamais ignorés ni inventés.
- **Ne jamais modifier les recettes ni le catalogue** depuis l'outil. Il lit
  `recettes/` et `donnees/`, il écrit uniquement dans `listes/`.

## Structure

```
courses-lafourche/
├── CLAUDE.md
├── README.md               # mode d'emploi court pour l'utilisatrice
├── courses.py              # point d'entrée CLI
├── courses/                # package
│   ├── extraction.py       # repère la section ingrédients d'une recette
│   ├── analyse.py          # ligne -> (quantité, unité, ingrédient)
│   ├── unites.py           # table des unités et conversions
│   ├── normalisation.py    # minuscules, accents, pluriels, alias
│   ├── fusion.py           # regroupement et addition des quantités
│   ├── catalogue.py        # lecture du CSV, correspondance, nb de produits
│   └── rendu.py            # génération du Markdown
├── donnees/
│   ├── catalogue.csv       # catalogue perso La Fourche
│   ├── alias.csv           # variantes -> nom canonique
│   └── placard.txt         # ingrédients toujours à la maison (ignorés)
├── recettes/               # NON versionné (.gitignore)
│   └── 2026-S41/
│       ├── curry-lentilles.txt
│       └── gratin-courge.txt
├── listes/                 # NON versionné (.gitignore)
│   └── 2026-S41.md
└── tests/
    ├── exemples/           # recettes de test, catalogue de test
    └── test_*.py
```

## Pile technique

- Python 3.11+, **bibliothèque standard uniquement** (`csv`, `re`, `pathlib`,
  `unicodedata`, `fractions`, `argparse`, `urllib.parse`). Pas de dépendance
  à installer.
- Tests avec `unittest` : `python3 -m unittest discover -s tests`.
- Lancer les tests avant chaque commit.

## Formats des fichiers

### Recettes — `recettes/AAAA-Sxx/*.txt`

Texte libre UTF-8, une recette par fichier, collé tel quel depuis le web.
Le nom du fichier sert de nom de recette dans la liste.

Repérage des ingrédients :
- Si une ligne contient « Ingrédients » (titre), on prend les lignes suivantes
  jusqu'au prochain titre (« Préparation », « Étapes », « Instructions »…) ou
  une ligne vide double.
- Sinon, on prend les lignes qui commencent par une puce (`-`, `•`, `*`) ou par
  un nombre.
- Les puces, numéros de liste et mentions entre parenthèses non quantitatives
  sont nettoyés.

Exemples de lignes à savoir analyser :

```
- 200 g de lentilles corail
• 2 oignons jaunes
1 c. à soupe de curry
3 cuillères à café de cumin
1/2 litre de lait de coco
1,5 kg de courge butternut
1 boîte de tomates concassées (400 g)
Sel, poivre
```

### Catalogue — `donnees/catalogue.csv`

UTF-8, séparateur `;` (compatible Excel français), première ligne = en-têtes.

```
ingredient;produit;lien;format
lentille corail;Lentilles corail bio 500 g;https://lafourche.fr/products/...;500 g
oignon jaune;Oignons jaunes bio filet 1 kg;https://lafourche.fr/products/...;1 kg
lait de coco;Lait de coco bio 400 ml;https://lafourche.fr/products/...;400 ml
curry;Curry en poudre bio 40 g;https://lafourche.fr/products/...;40 g
```

- `ingredient` : nom canonique (minuscule, singulier) — c'est la clé de
  correspondance.
- `format` : `<nombre> <unité>` (`500 g`, `1 L`, `6 pièces`). Sert à calculer
  le nombre de produits à commander (arrondi au supérieur). Si le format est
  vide ou incompatible avec l'unité du besoin, on affiche le besoin sans calcul.
- Une ligne en double sur `ingredient` = erreur explicite au chargement.

### Alias — `donnees/alias.csv`

```
variante;ingredient
oignons jaunes;oignon jaune
lentilles corail;lentille corail
lentilles corail décortiquées;lentille corail
butternut;courge butternut
```

Appliqué après la normalisation automatique (minuscules, espaces, pluriel
simple en -s/-x). Les alias servent pour ce que la règle automatique ne couvre
pas.

### Placard — `donnees/placard.txt`

Un ingrédient canonique par ligne (`sel`, `poivre`, `huile d'olive`…).
Ces ingrédients n'apparaissent pas dans « À commander » mais dans une section
repliée « Supposés au placard » pour vérification.

### Liste de courses — `listes/AAAA-Sxx.md`

```markdown
# Courses — semaine 2026-S41

Recettes : curry-lentilles, gratin-courge

## À commander (catalogue)
- [ ] **Lentilles corail bio 500 g** × 1 — besoin : 200 g — [ouvrir](https://…)
- [ ] **Oignons jaunes bio filet 1 kg** × 1 — besoin : 3 pièces — [ouvrir](https://…)

## Absents du catalogue — à chercher
- [ ] courge butternut — besoin : 1,5 kg — [rechercher sur La Fourche](https://…)

## À vérifier
- « 1 boîte de tomates concassées » : unité « boîte » non additionnable avec « g »
- curry-lentilles.txt, ligne « Une belle poignée d'herbes » : non comprise

<details><summary>Supposés au placard</summary>

- sel, poivre
</details>
```

## Règles métier

- **Unités** : masses ramenées en g, volumes en ml, cuillères
  (`c. à s.` = cuillère à soupe, `c. à c.` = cuillère à café) gardées telles
  quelles, comptables en « pièces ». On n'additionne que des unités de la même
  famille ; sinon on liste les quantités séparément (`200 g + 1 boîte`).
- **Pas de conversion volume ↔ masse** ni cuillère ↔ g : trop approximatif.
- **Nombres** : accepter `1,5`, `1.5`, `1/2`, `½`, `1 1/2`, « un », « une ».
- **Sans quantité** (« sel, poivre », « quelques feuilles de basilic ») :
  ingrédient retenu avec la mention « quantité non précisée ».
- **Affichage** : virgule décimale française, kg/L au-delà de 1000 g/ml.
- **Lien de recherche** : construit avec `urllib.parse.quote` à partir du nom
  canonique, sur un modèle d'URL défini en **une seule constante** dans
  `catalogue.py` (`URL_RECHERCHE`), à vérifier à la main par l'utilisatrice.
- **Ordre de la liste** : alphabétique par ingrédient dans chaque section.

## Confidentialité

Le dépôt est publié sur GitHub Pages (`.github/workflows/deploy.yml` publie
tout le dépôt). Les dossiers `recettes/` et `listes/` sont donc dans
`.gitignore`. Le catalogue peut être versionné (il ne contient que des liens
publics) ; ne jamais y mettre d'identifiants ou de lien de compte personnel.

## Hors périmètre (pour l'instant)

- Ajustement au nombre de personnes.
- Remplissage automatique du panier La Fourche.
- Interface web.
- Extraction par IA des lignes non comprises (envisageable plus tard, en
  option, sans jamais remplacer le signalement).
