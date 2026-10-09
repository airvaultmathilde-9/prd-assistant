# Courses La Fourche

Petite page web personnelle qui transforme les recettes de la semaine en liste
de courses à commander sur La Fourche (épicerie bio en ligne).

Elle existe en deux exemplaires, construits à partir des mêmes fichiers :
- **Version claude.ai** (principale) : publiée comme Artifact, avec les
  capacités `sample` (demander à Claude) et `downloads` (exporter un CSV).
  C'est la seule où les ingrédients peuvent être générés.
- **Version GitHub Pages** : `…/prd-assistant/courses-lafourche/`, dans le dépôt
  `prd-assistant` à côté de `running-coach/` et `job-analyzer/`. Sans Claude :
  on y colle la liste d'ingrédients à la main.

## Ce que fait la page

1. **Recettes** : pour chaque recette, l'utilisatrice écrit un nom ou une
   courte description et un nombre de personnes, puis clique « Générer les
   ingrédients ». Claude renvoie la liste (JSON validé puis converti en lignes
   de texte) dans une zone éditable : elle relit et corrige. Elle peut aussi y
   coller une recette entière copiée du web.
2. La page extrait les lignes d'ingrédients, analyse quantité / unité / nom,
   normalise les noms (minuscules, singulier, alias), fusionne les doublons et
   additionne les quantités compatibles.
3. Elle déduit ce qui est **déjà à la maison** (tableau stock).
4. Elle associe le reste aux **produits La Fourche déjà commandés** (tableau
   produits) et calcule le nombre de produits quand le format le permet.
5. **Liste** : À commander (lien produit), À chercher sur La Fourche (lien de
   recherche + « + Mes produits » / « J'en ai déjà »), À vérifier, Déjà à la
   maison ; cases à cocher, copie en Markdown, impression (Pages uniquement).
6. **Catalogue** : deux tableaux éditables, plus les alias en réglage avancé.
   - *Mes produits La Fourche* : on colle des liens de fiches produit (un par
     ligne) ; ingrédient, nom et format sont déduits du texte de l'adresse,
     puis affinés par Claude s'il est disponible. Import/export CSV.
   - *Déjà à la maison* : ingrédient + quantité facultative (vide = assez).

## Règles absolues

- **Aucun accès réseau au site La Fourche.** Pas de scraping, pas de `fetch`,
  pas d'appel à une API non officielle : leur `robots.txt` l'interdit.
  La page ne fait que *construire* des URL (liens produit, liens de recherche)
  que l'utilisatrice ouvre elle-même (`target="_blank"`). Claude ne peut pas
  ouvrir les liens non plus : il ne lit que le texte de l'adresse.
  Cela vaut aussi pour Claude pendant le développement : ne pas utiliser
  WebFetch, curl ou un navigateur sur lafourche.fr.
- **Données** : recettes, produits, stock et alias restent dans le
  `localStorage` du navigateur. Seule exception : sur un clic, la version
  claude.ai envoie à Claude le nom de la recette, le nombre de personnes et les
  noms d'ingrédients déjà connus (ou les liens collés). Rien d'autre, jamais au
  chargement, jamais en boucle. Pas de serveur, pas d'analytics.
- **Ce que Claude génère est relu.** Les ingrédients générés s'affichent dans
  la zone éditable avant de compter dans la liste ; les produits déduits des
  liens sont modifiables. Une réponse mal formée est refusée avec un message,
  jamais devinée.
- **Ne jamais deviner silencieusement.** Une ligne non comprise, un ingrédient
  absent des produits, des unités impossibles à additionner ou un stock non
  comparable sont *signalés* dans « À vérifier », jamais ignorés ni inventés.
- **Tout en français** : interface, messages, liste générée, consignes envoyées
  à Claude, commentaires du code.

## Structure

```
courses-lafourche/
├── CLAUDE.md
├── index.html              # la page (onglets : Recettes, Liste, Catalogue)
├── styles.css
├── app.js                  # interface, localStorage, appels à Claude
├── moteur/                 # logique pure, sans DOM, testable avec Node
│   ├── extraction.js       # repère les lignes d'ingrédients d'un texte
│   ├── analyse.js          # ligne -> { quantite, unite, nom }
│   ├── unites.js           # table des unités, conversions, affichage
│   ├── normalisation.js    # minuscules, accents, pluriels, alias
│   ├── fusion.js           # regroupement et addition des quantités
│   ├── catalogue.js        # CSV, validation des produits, nb de produits
│   ├── generation.js       # consignes pour Claude, validation des réponses,
│   │                       # devinette produit/format depuis une URL
│   ├── liste.js            # assemble la liste (stock, produits, recherche)
│   └── rendu.js            # liste -> Markdown
├── package.json            # uniquement "type": "module" et le script de test
├── donnees/
│   ├── alias-defaut.csv    # alias proposés au premier lancement
│   └── placard-defaut.txt  # « déjà à la maison » proposé au premier lancement
└── tests/
    └── *.test.js           # node --test
```

## Pile technique

- HTML + CSS + JavaScript « vanilla » en modules ES. Aucun framework, aucune
  étape de build, aucune dépendance npm.
- `moteur/` ne touche jamais au DOM, au `localStorage` ni à Claude : fonctions
  pures, entrées → sorties. Les appels à Claude sont dans `app.js`.
- Claude est atteint par `window.claude.use('sample')` (`sample.json`,
  `modelTier: 'quick'`), seulement si `window.claude` existe ; sinon le bouton
  de génération n'est pas affiché. Erreurs : messages par `code`
  (`not_granted`, `rate_limited`, `invalid_json`…), jamais de nouvel essai
  automatique.
- Le cadre claude.ai bloque `confirm()`, `window.print()` et les liens de
  téléchargement : confirmations par double clic (`boutonConfirme`), pas de
  bouton Imprimer dans claude.ai, export CSV par la capacité `downloads`.
- Tests : `npm test` (= `node --test tests/*.test.js`). Les lancer avant
  chaque commit.
- Interface utilisable sur téléphone, thèmes clair et sombre (tokens CSS,
  `prefers-color-scheme` et `data-theme`).

### Publier la version claude.ai

Copier `index.html`, `styles.css`, `app.js`, `moteur/` et `donnees/` dans un
dossier de travail ; dans `index.html`, ne garder que `<title>`, le lien vers
`styles.css` et le contenu de `<body>` (l'Artifact ajoute lui-même doctype et
`<head>`). Publier avec `capabilities: { sample: {}, downloads: true }` sur la
même URL d'Artifact pour conserver les données des navigateurs.

## Données (localStorage, clé `courses-lafourche:v1`)

```js
{
  onglet: 'recettes' | 'liste' | 'catalogue',
  recettes: [{ id, nom, personnes, ingredients }],   // ingredients : texte
  catalogue: [{ id, ingredient, produit, lien, format }],
  stock: [{ id, ingredient, quantite }],              // quantite '' = assez
  alias: 'variante;ingredient\n…',                    // texte CSV
  coches: { 'c:<cle>': true },
}
```

`migrer()` dans `app.js` reprend les anciens formats (`texte` → `ingredients`,
`placard` → `stock`).

### CSV des produits

UTF-8 (BOM à l'export), séparateur `;`, en-têtes `ingredient;produit;lien;format`.
À l'import : `,` et en-têtes accentués acceptés ; lien hors
`https://lafourche.fr/` refusé ; doublon d'ingrédient signalé.

```
ingredient;produit;lien;format
pois chiche;La Fourche Pois chiches bio 265 g;https://lafourche.fr/products/la-fourche-pois-chiches-bio-0-265kg;265 g
```

Liens produit : `https://lafourche.fr/products/<identifiant>` ; l'identifiant
finit souvent par le format (`-0-265kg` = 0,265 kg, `-400ml`).
Lien de recherche : `https://lafourche.fr/search?query=<terme encodé>`
(constante `URL_RECHERCHE` dans `moteur/catalogue.js`).

## Règles métier

- **Unités** : masses en g, volumes en ml, cuillères (`c. à soupe`,
  `c. à café`) telles quelles, comptables en « pièces », contenants (boîte,
  gousse, botte…) chacun à part. On n'additionne que la même famille.
- **Pas de conversion volume ↔ masse** ni cuillère ↔ g.
- **Nombres** : `1,5`, `1.5`, `1/2`, `½`, `1 1/2`, « un », « une », « un
  demi » ; fourchette `2 à 3` → maximum, signalé.
- **Sans quantité** (« sel, poivre ») : « quantité non précisée ».
- **Stock** : sans quantité = couvre tout le besoin ; avec quantité de la même
  unité = déduite ; unité différente = rien déduit, signalé.
- **Nombre de produits** : arrondi au supérieur, seulement si le format et le
  besoin sont dans la même unité.
- **Affichage** : virgule décimale, kg/L au-delà de 1000 g/ml, ordre
  alphabétique dans chaque section.

## Sécurité

- Le dépôt entier est publié sur GitHub Pages : ne jamais y versionner de
  recettes ni de produits personnels (seuls `donnees/*-defaut.*`).
- Tout texte venant de l'utilisatrice ou de Claude est inséré via des nœuds
  texte, jamais `innerHTML`. Les réponses de Claude sont validées (types,
  longueurs, unités autorisées) avant usage.
- Liens créés avec `rel="noopener noreferrer"`.
- Toute lecture/écriture `localStorage` est protégée par `try/catch`.

## Hors périmètre (pour l'instant)

- Remplissage automatique du panier La Fourche.
- Synchronisation entre appareils (passer par l'export/import CSV).
