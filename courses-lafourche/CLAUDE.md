# Courses La Fourche

Petite page web personnelle qui transforme les recettes de la semaine en liste
de courses à commander sur La Fourche (épicerie bio en ligne).

Elle fait partie du dépôt `prd-assistant`, à côté de `running-coach/` et
`job-analyzer/`, et est publiée par GitHub Pages à l'adresse
`…/courses-lafourche/`.

## Ce que fait la page

1. L'utilisatrice colle ses recettes de la semaine (une zone de texte par
   recette, avec un nom ; bouton « + recette »).
2. La page extrait les lignes d'ingrédients de chaque recette (texte libre
   copié du web).
3. Elle analyse chaque ligne : quantité, unité, ingrédient.
4. Elle normalise le nom de l'ingrédient (minuscules, singulier, alias).
5. Elle fusionne les doublons et additionne les quantités compatibles.
6. Elle associe chaque ingrédient à un produit du catalogue perso.
7. Elle calcule le nombre de produits à commander quand le format le permet.
8. Elle affiche la liste de courses (cases à cocher, liens cliquables), qu'on
   peut copier en texte/Markdown ou imprimer.

## Règles absolues

- **Aucun accès réseau au site La Fourche.** Pas de scraping, pas de `fetch`,
  pas d'appel à une API non officielle : leur `robots.txt` l'interdit.
  La page ne fait que *construire* des URL (liens produit du catalogue, liens
  de recherche) que l'utilisatrice ouvre elle-même (`target="_blank"`).
  Cela vaut aussi pour Claude pendant le développement : ne pas utiliser
  WebFetch, curl ou un navigateur sur lafourche.fr pour remplir le catalogue
  ou vérifier des produits.
- **Aucune donnée personnelle ne quitte le navigateur.** Pas de serveur, pas
  d'analytics, pas de service tiers. Recettes, catalogue, alias et placard
  sont stockés dans le `localStorage` du navigateur.
- **Tout en français** : textes de l'interface, messages d'erreur, liste
  générée, commentaires du code. Les identifiants de code peuvent être en
  français sans accents.
- **Ne jamais deviner silencieusement.** Une ligne non comprise, un ingrédient
  absent du catalogue ou des unités impossibles à additionner sont *signalés*
  dans la liste, jamais ignorés ni inventés.

## Structure

```
courses-lafourche/
├── CLAUDE.md
├── index.html              # la page (onglets : Recettes, Liste, Catalogue)
├── styles.css
├── app.js                  # interface : DOM, événements, localStorage
├── moteur/                 # logique pure, sans DOM, testable avec Node
│   ├── extraction.js       # repère la section ingrédients d'une recette
│   ├── analyse.js          # ligne -> { quantite, unite, ingredient }
│   ├── unites.js           # table des unités et conversions
│   ├── normalisation.js    # minuscules, espaces, pluriels, alias
│   ├── fusion.js           # regroupement et addition des quantités
│   ├── catalogue.js        # CSV <-> objets, correspondance, nb de produits
│   └── rendu.js            # liste -> Markdown (copie / export)
├── donnees/
│   ├── alias-defaut.csv    # alias proposés au premier lancement
│   └── placard-defaut.txt  # placard proposé au premier lancement
└── tests/
    └── *.test.js           # node --test
```

## Pile technique

- HTML + CSS + JavaScript « vanilla » en modules ES (`<script type="module">`).
  Aucun framework, aucune étape de build, aucune dépendance npm : la page
  doit fonctionner telle quelle sur GitHub Pages.
- La logique (`moteur/`) ne touche jamais au DOM ni au `localStorage` :
  fonctions pures, entrées → sorties.
- Tests : `node --test tests/` (Node 20+, module `node:test` intégré).
  Lancer les tests avant chaque commit.
- Interface utilisable sur téléphone (mise en page fluide, pas de défilement
  horizontal).

## Données et formats

### Recettes

Saisies dans la page : un nom + un texte libre collé tel quel depuis le web.
Conservées dans le `localStorage` jusqu'à ce que l'utilisatrice clique
« Vider la semaine ». Jamais versionnées.

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

### Catalogue

Modifiable dans l'onglet « Catalogue » (tableau éditable), conservé dans le
`localStorage`. Boutons **Importer CSV** et **Exporter CSV** pour le
sauvegarder ou l'éditer dans Excel.

Format CSV : UTF-8, séparateur `;` (compatible Excel français), première
ligne = en-têtes. À l'import, accepter aussi `,` et le BOM UTF-8 d'Excel.

```
ingredient;produit;lien;format
pois chiche;La Fourche Pois chiches bio 265 g;https://lafourche.fr/products/la-fourche-pois-chiches-bio-0-265kg;265 g
lentille corail;Lentilles corail bio 500 g;https://lafourche.fr/products/...;500 g
oignon jaune;Oignons jaunes bio filet 1 kg;https://lafourche.fr/products/...;1 kg
lait de coco;Lait de coco bio 400 ml;https://lafourche.fr/products/...;400 ml
```

- `ingredient` : nom canonique (minuscule, singulier) — clé de correspondance.
- `produit` : nom affiché dans la liste.
- `lien` : URL produit copiée depuis le navigateur, de la forme
  `https://lafourche.fr/products/<identifiant>`. Refuser à l'import tout lien
  qui ne commence pas par `https://lafourche.fr/`.
- `format` : `<nombre> <unité>` (`500 g`, `1 L`, `6 pièces`). Sert à calculer
  le nombre de produits à commander (arrondi au supérieur). Si le format est
  vide ou incompatible avec l'unité du besoin, on affiche le besoin sans calcul.
- Deux lignes avec le même `ingredient` : erreur affichée à l'import.

Depuis la liste, un ingrédient absent du catalogue a un bouton
« Ajouter au catalogue » qui pré-remplit une ligne (l'utilisatrice colle
elle-même le lien et le format).

### Alias

Même principe (onglet Catalogue, section Alias), format `variante;ingredient` :

```
variante;ingredient
oignons jaunes;oignon jaune
lentilles corail décortiquées;lentille corail
butternut;courge butternut
```

Appliqués après la normalisation automatique (minuscules, espaces, pluriel
simple en -s/-x). Valeurs initiales chargées depuis `donnees/alias-defaut.csv`
au premier lancement uniquement.

### Placard

Liste d'ingrédients toujours à la maison (`sel`, `poivre`, `huile d'olive`…),
éditable dans la page. Valeurs initiales depuis `donnees/placard-defaut.txt`.
Ils n'apparaissent pas dans « À commander » mais dans une section repliée
« Supposés au placard » pour vérification.

### Liste de courses (affichage et export Markdown)

```markdown
# Courses — semaine du 12 octobre 2026

Recettes : Curry de lentilles, Gratin de courge

## À commander (catalogue)
- [ ] **Lentilles corail bio 500 g** × 1 — besoin : 200 g — [ouvrir](https://…)
- [ ] **Oignons jaunes bio filet 1 kg** × 1 — besoin : 3 pièces — [ouvrir](https://…)

## Absents du catalogue — à chercher
- [ ] courge butternut — besoin : 1,5 kg — [rechercher sur La Fourche](https://…)

## À vérifier
- tomates concassées : « 1 boîte » et « 400 g » non additionnables
- Curry de lentilles, ligne « Une belle poignée d'herbes » : non comprise

<details><summary>Supposés au placard</summary>

- sel, poivre
</details>
```

Chaque ligne indique de quelle(s) recette(s) vient le besoin (au survol ou en
petit texte), pour pouvoir vérifier.

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
- **Lien de recherche** : construit avec `encodeURIComponent` à partir du nom
  canonique, sur un modèle d'URL défini en **une seule constante**
  (`URL_RECHERCHE` dans `moteur/catalogue.js`) :
  `https://lafourche.fr/search?query=<terme encodé>`
  (ex. `https://lafourche.fr/search?query=lentilles%20corail`), format
  confirmé par l'utilisatrice.
- **Ordre de la liste** : alphabétique par ingrédient dans chaque section.

## Sécurité et confidentialité

- Le dépôt entier est publié sur GitHub Pages : ne jamais y versionner de
  recettes, de liste ni de catalogue personnel. Seuls les fichiers
  `donnees/*-defaut.*` (génériques) sont versionnés.
- Tout texte venant de l'utilisatrice (recettes, CSV importé) est inséré dans
  le DOM via `textContent`, jamais via `innerHTML`.
- Les liens sont créés avec `rel="noopener noreferrer"`.
- Toute lecture/écriture `localStorage` est protégée par `try/catch` ; la page
  fonctionne (sans mémorisation) si le stockage est indisponible.

## Hors périmètre (pour l'instant)

- Ajustement au nombre de personnes.
- Remplissage automatique du panier La Fourche.
- Synchronisation entre appareils (passer par Exporter/Importer CSV).
- Extraction par IA des lignes non comprises (envisageable plus tard, en
  option, sans jamais remplacer le signalement).
