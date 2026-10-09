// Interface : onglets, recettes, liste, catalogue, stockage local.
// Toute la logique métier est dans moteur/ ; ici on ne fait que l'affichage
// et les appels à Claude (capacité « sample », seulement dans la version
// publiée sur claude.ai, et seulement sur un clic).
// Règle : aucun innerHTML, tout texte utilisateur passe par des nœuds texte.

import { genererListe, formatBesoins } from './moteur/liste.js';
import { enMarkdown, titreListe } from './moteur/rendu.js';
import {
  validerCatalogue, lireCatalogue, catalogueEnCSV, lireAlias, lirePlacard, lienValide, PREFIXE_LIEN,
} from './moteur/catalogue.js';
import {
  consigneIngredients, lignesDepuisReponse, devinerDepuisLien, consigneProduits, produitsDepuisReponse,
} from './moteur/generation.js';
import { lireFormat } from './moteur/unites.js';

const CLE_STOCKAGE = 'courses-lafourche:v1';
const ANCIENNES_CLES = ['courses-lafourche:apercu'];
const ONGLETS = ['recettes', 'liste', 'catalogue'];
const DANS_CLAUDE = typeof window.claude?.use === 'function';

const $app = document.getElementById('app');
const $toasts = document.getElementById('toasts');

let etat = null;
let stockageOk = true;
let erreursImport = [];
let claudeSample = null; // fonction sample, ou null si indisponible
let claudeDownloads = null;

// ── Stockage ──────────────────────────────────────────────────────────

const nouvelId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

function nouvelleRecette(personnes = 2) {
  return { id: nouvelId(), nom: '', personnes, ingredients: '' };
}

function charger() {
  try {
    for (const k of [CLE_STOCKAGE, ...ANCIENNES_CLES]) {
      const brut = localStorage.getItem(k);
      if (brut) return JSON.parse(brut);
    }
    return null;
  } catch {
    stockageOk = false;
    return null;
  }
}

let minuterie = null;
function sauver() {
  clearTimeout(minuterie);
  minuterie = setTimeout(() => {
    try {
      localStorage.setItem(CLE_STOCKAGE, JSON.stringify(etat));
    } catch {
      stockageOk = false;
      document.getElementById('alerte-stockage').hidden = false;
    }
  }, 250);
}

async function lireDefaut(chemin) {
  try {
    const r = await fetch(chemin);
    return r.ok ? await r.text() : '';
  } catch {
    return '';
  }
}

// Met à jour un état sauvegardé par une version précédente de la page.
function migrer(e) {
  e.recettes = (e.recettes || []).map((r) => ({
    id: r.id || nouvelId(),
    nom: r.nom || '',
    personnes: Number(r.personnes) || 2,
    ingredients: r.ingredients ?? r.texte ?? '',
  }));
  if (!Array.isArray(e.stock)) {
    e.stock = lirePlacard(e.placard || '').map((ingredient) => ({ id: nouvelId(), ingredient, quantite: '' }));
  }
  delete e.placard;
  e.catalogue = (e.catalogue || []).map((p) => ({ ...p, id: p.id || nouvelId() }));
  e.stock = e.stock.map((s) => ({ ...s, id: s.id || nouvelId() }));
  return e;
}

async function initialiser() {
  const sauvegarde = charger();
  if (sauvegarde) {
    etat = migrer({ onglet: 'recettes', coches: {}, alias: '', ...sauvegarde });
  } else {
    const placard = lirePlacard(await lireDefaut('donnees/placard-defaut.txt'));
    etat = {
      onglet: 'recettes',
      recettes: [{
        id: nouvelId(),
        nom: 'Exemple : curry de lentilles corail',
        personnes: 4,
        ingredients: '- 300 g de lentilles corail\n- 2 oignons jaunes\n- 400 ml de lait de coco\n- 1 boîte de tomates concassées\n- 2 c. à soupe de curry\n- sel',
      }],
      catalogue: [{
        id: nouvelId(),
        ingredient: 'pois chiche',
        produit: 'La Fourche Pois chiches bio 265 g',
        lien: 'https://lafourche.fr/products/la-fourche-pois-chiches-bio-0-265kg',
        format: '265 g',
      }],
      stock: placard.map((ingredient) => ({ id: nouvelId(), ingredient, quantite: '' })),
      alias: await lireDefaut('donnees/alias-defaut.csv'),
      coches: {},
    };
    sauver();
  }
  if (!etat.recettes.length) etat.recettes.push(nouvelleRecette());
  if (!ONGLETS.includes(etat.onglet)) etat.onglet = 'recettes';
  document.getElementById('alerte-stockage').hidden = stockageOk;

  for (const b of document.querySelectorAll('[data-onglet]')) {
    b.addEventListener('click', () => allerA(b.dataset.onglet));
  }
  afficher();

  // Capacités claude.ai : elles arrivent après le premier affichage.
  if (DANS_CLAUDE) {
    window.claude.use('sample').then((s) => { claudeSample = s; if (s) afficher(); }).catch(() => {});
    window.claude.use('downloads').then((d) => { claudeDownloads = d; }).catch(() => {});
  }
}

// ── Outils DOM ────────────────────────────────────────────────────────

function el(tag, props = {}, ...enfants) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null) continue;
    if (k === 'class') n.className = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (k in n) n[k] = v;
    else n.setAttribute(k, v);
  }
  for (const e of enfants.flat()) {
    if (e === null || e === undefined || e === false) continue;
    n.append(e instanceof Node ? e : document.createTextNode(String(e)));
  }
  return n;
}

function lienExterne(href, texte) {
  return el('a', { href, target: '_blank', rel: 'noopener noreferrer' }, texte);
}

function toast(message) {
  const t = el('div', { class: 'toast' }, message);
  $toasts.append(t);
  setTimeout(() => t.remove(), 4000);
}

function blocErreurs(titre, erreurs) {
  if (!erreurs.length) return null;
  return el('div', { class: 'erreurs', role: 'alert' },
    el('strong', {}, titre),
    el('ul', {}, erreurs.map((e) => el('li', {}, e))));
}

// Bouton à double clic de confirmation (pas de confirm(), bloqué sur claude.ai).
function boutonConfirme(libelle, libelleConfirmer, action, classe = 'bouton danger') {
  let arme = false;
  let minuteur = null;
  const b = el('button', {
    type: 'button',
    class: classe,
    onclick: () => {
      if (!arme) {
        arme = true;
        b.textContent = libelleConfirmer;
        minuteur = setTimeout(() => { arme = false; b.textContent = libelle; }, 4000);
        return;
      }
      clearTimeout(minuteur);
      action();
    },
  }, libelle);
  return b;
}

function allerA(onglet) {
  etat.onglet = onglet;
  sauver();
  afficher();
  window.scrollTo(0, 0);
}

function afficher() {
  for (const b of document.querySelectorAll('[data-onglet]')) {
    b.setAttribute('aria-selected', String(b.dataset.onglet === etat.onglet));
  }
  const vues = { recettes: vueRecettes, liste: vueListe, catalogue: vueCatalogue };
  $app.replaceChildren(...vues[etat.onglet]());
}

const MESSAGES_CLAUDE = {
  not_granted: 'Tu as refusé l\'accès à Claude pour cette page. Recharge la page pour qu\'il te soit redemandé.',
  rate_limited: 'Trop de demandes d\'un coup. Attends un peu puis réessaie.',
  invalid_json: 'La réponse de Claude était mal formée. Réessaie.',
  refused: 'Claude n\'a pas voulu répondre à cette demande. Reformule le nom de la recette.',
  cancelled: 'Demande annulée.',
};
const messageClaude = (e) => MESSAGES_CLAUDE[e?.code] || `La demande à Claude a échoué (${e?.code || e?.message || 'erreur inconnue'}). Réessaie.`;

// ── Données dérivées ──────────────────────────────────────────────────

function donneesPerso() {
  return {
    catalogue: validerCatalogue(etat.catalogue),
    alias: lireAlias(etat.alias || 'variante;ingredient\n'),
  };
}

function nomsConnus() {
  const noms = [...etat.catalogue, ...etat.stock].map((x) => (x.ingredient || '').trim()).filter(Boolean);
  return [...new Set(noms)];
}

// ── Vue : recettes ────────────────────────────────────────────────────

async function genererIngredients(r, $bouton, $zone, $etat) {
  if (!r.nom.trim()) {
    $etat.textContent = 'Indique d\'abord le nom ou la description de la recette.';
    return;
  }
  if (r.ingredients.trim() && $bouton.dataset.remplacer !== 'oui') {
    $bouton.dataset.remplacer = 'oui';
    $bouton.textContent = 'Remplacer les ingrédients ?';
    setTimeout(() => { $bouton.dataset.remplacer = ''; $bouton.textContent = 'Générer les ingrédients'; }, 4000);
    return;
  }
  $bouton.dataset.remplacer = '';
  $bouton.disabled = true;
  $bouton.textContent = 'Claude réfléchit…';
  $etat.textContent = '';
  try {
    const reponse = await claudeSample.json(
      consigneIngredients({ recette: r.nom.trim(), personnes: r.personnes, nomsConnus: nomsConnus() }),
      { modelTier: 'quick' },
    );
    const { lignes, ignorees } = lignesDepuisReponse(reponse);
    if (!lignes.length) throw new Error('Aucun ingrédient dans la réponse.');
    r.ingredients = lignes.join('\n');
    $zone.value = r.ingredients;
    sauver();
    $etat.textContent = `${lignes.length} ingrédients pour ${r.personnes} personne${r.personnes > 1 ? 's' : ''}. Relis et corrige si besoin.${ignorees ? ` ${ignorees} ligne(s) mal formée(s) mise(s) sans quantité.` : ''}`;
  } catch (e) {
    $etat.textContent = e?.code ? messageClaude(e) : `Réponse inutilisable : ${e.message}`;
  } finally {
    $bouton.disabled = false;
    $bouton.textContent = 'Générer les ingrédients';
  }
}

function carteRecette(r, i) {
  const $etat = el('p', { class: 'aide', 'aria-live': 'polite' });
  const $zone = el('textarea', {
    id: `ingredients-${r.id}`,
    value: r.ingredients,
    placeholder: claudeSample
      ? 'Les ingrédients générés apparaîtront ici. Tu peux aussi coller une recette entière.'
      : 'Colle ici la liste des ingrédients, ou la recette entière copiée du web.',
    'aria-label': `Ingrédients de la recette ${i + 1}`,
    oninput: (e) => { r.ingredients = e.target.value; sauver(); },
  });
  const $generer = el('button', {
    type: 'button',
    class: 'bouton principal',
    onclick: () => genererIngredients(r, $generer, $zone, $etat),
  }, 'Générer les ingrédients');

  return el('section', { class: 'carte recette' },
    el('div', { class: 'recette-entete' },
      el('label', { class: 'champ champ-nom' },
        el('span', { class: 'etiquette' }, 'Recette'),
        el('input', {
          id: `nom-${r.id}`,
          type: 'text',
          value: r.nom,
          placeholder: 'ex. curry de lentilles corail, lasagnes végétariennes…',
          oninput: (e) => { r.nom = e.target.value; sauver(); },
        })),
      el('label', { class: 'champ champ-personnes' },
        el('span', { class: 'etiquette' }, 'Personnes'),
        el('input', {
          id: `personnes-${r.id}`,
          type: 'number',
          min: 1,
          max: 30,
          value: r.personnes,
          oninput: (e) => {
            const n = Math.round(Number(e.target.value));
            if (n >= 1 && n <= 30) { r.personnes = n; sauver(); }
          },
        })),
      el('button', {
        type: 'button',
        class: 'bouton-icone',
        title: 'Supprimer cette recette',
        'aria-label': 'Supprimer cette recette',
        onclick: () => {
          etat.recettes.splice(i, 1);
          if (!etat.recettes.length) etat.recettes.push(nouvelleRecette());
          sauver();
          afficher();
          toast('Recette supprimée.');
        },
      }, '✕')),
    claudeSample ? el('div', { class: 'barre' }, $generer) : null,
    $etat,
    $zone);
}

function vueRecettes() {
  return [
    el('p', { class: 'aide' },
      claudeSample
        ? 'Écris le nom de chaque recette et le nombre de personnes, puis « Générer les ingrédients ». Claude propose la liste, tu la relis, puis tu génères la liste de courses.'
        : DANS_CLAUDE
          ? 'Connexion à Claude en cours… En attendant, tu peux coller une liste d\'ingrédients.'
          : 'La génération automatique des ingrédients fonctionne dans la version claude.ai de cette page. Ici, colle la liste des ingrédients de chaque recette.'),
    ...etat.recettes.map(carteRecette),
    el('div', { class: 'barre' },
      el('button', {
        type: 'button',
        class: 'bouton',
        onclick: () => {
          const derniere = etat.recettes[etat.recettes.length - 1];
          etat.recettes.push(nouvelleRecette(derniere?.personnes || 2));
          sauver();
          afficher();
          const champs = $app.querySelectorAll('.champ-nom input');
          champs[champs.length - 1]?.focus();
        },
      }, '+ Recette'),
      el('span', { class: 'espace' }),
      boutonConfirme('Vider la semaine', 'Confirmer : tout vider', () => {
        etat.recettes = [nouvelleRecette(etat.recettes[0]?.personnes || 2)];
        etat.coches = {};
        sauver();
        afficher();
        toast('Semaine vidée.');
      }),
      el('button', { type: 'button', class: 'bouton principal', onclick: () => allerA('liste') }, 'Générer la liste →')),
  ];
}

// ── Vue : liste ───────────────────────────────────────────────────────

function origines(item) {
  const recettes = [...new Set(item.origines.map((o) => o.recette))];
  const lignes = item.origines.map((o) => `${o.recette} : ${o.original}`).join('\n');
  return el('span', { class: 'item-origine', title: lignes }, recettes.join(' · '));
}

function caseACocher(cleCoche, li) {
  const coche = Boolean(etat.coches[cleCoche]);
  if (coche) li.classList.add('coche');
  return el('input', {
    type: 'checkbox',
    checked: coche,
    'aria-label': 'Fait',
    onchange: (e) => {
      if (e.target.checked) etat.coches[cleCoche] = true;
      else delete etat.coches[cleCoche];
      li.classList.toggle('coche', e.target.checked);
      sauver();
    },
  });
}

const texteBesoin = (item) => `${formatBesoins(item.besoins, item.sansQuantite)}${item.stock ? ` (${item.stock} déduit)` : ''}`;

function itemCommande(item) {
  const li = el('li', { class: 'item' });
  const nombre = item.nombre
    ? el('span', { class: 'item-nombre' }, `× ${item.nombre}`)
    : el('span', { class: 'item-nombre', title: 'Nombre non calculable : format absent ou unités différentes' }, '× ?');
  li.append(
    caseACocher(`c:${item.cle}`, li),
    el('div', { class: 'item-corps' },
      el('div', { class: 'item-ligne' },
        el('span', { class: 'item-nom' }, item.produit),
        nombre,
        item.lien ? lienExterne(item.lien, 'Ouvrir ↗') : el('span', { class: 'aide' }, 'pas de lien')),
      el('span', { class: 'item-besoin' }, `Besoin : ${texteBesoin(item)}${item.format ? ` — format ${item.format}` : ''}`),
      origines(item)));
  return li;
}

function itemAChercher(item) {
  const li = el('li', { class: 'item' });
  li.append(
    caseACocher(`r:${item.cle}`, li),
    el('div', { class: 'item-corps' },
      el('div', { class: 'item-ligne' },
        el('span', { class: 'item-nom' }, item.nom),
        el('span', { class: 'item-besoin' }, texteBesoin(item))),
      origines(item),
      el('div', { class: 'item-actions pas-impression' },
        lienExterne(item.lienRecherche, 'Rechercher sur La Fourche ↗'),
        el('button', { type: 'button', class: 'bouton petit', onclick: () => ajouterProduitVide(item.nom) }, '+ Mes produits'),
        el('button', { type: 'button', class: 'bouton petit', onclick: () => ajouterStock(item.nom) }, 'J\'en ai déjà'))));
  return li;
}

function vueListe() {
  const { catalogue, alias } = donneesPerso();
  const recettes = etat.recettes
    .filter((r) => r.ingredients.trim())
    .map((r) => ({ nom: r.nom.trim() ? `${r.nom.trim()} (${r.personnes} p.)` : '', texte: r.ingredients }));
  if (!recettes.length) {
    return [el('section', { class: 'carte' },
      el('p', { class: 'vide' }, 'Aucune recette avec des ingrédients pour l\'instant.'),
      el('div', { class: 'barre' },
        el('button', { type: 'button', class: 'bouton principal', onclick: () => allerA('recettes') }, 'Ajouter des recettes')))];
  }

  const liste = genererListe({ recettes, catalogue: catalogue.entrees, alias: alias.alias, stock: etat.stock });
  const titre = titreListe();
  const erreursDonnees = [...catalogue.erreurs, ...alias.erreurs];

  const blocs = [
    el('section', { class: 'carte' },
      el('h2', { class: 'liste-titre' }, titre),
      el('p', { class: 'aide' }, `Recettes : ${liste.recettes.join(', ')}`),
      el('div', { class: 'barre pas-impression' },
        el('button', { type: 'button', class: 'bouton', onclick: () => copier(enMarkdown(liste, titre), 'Liste copiée.') }, 'Copier la liste'),
        DANS_CLAUDE ? null : el('button', { type: 'button', class: 'bouton', onclick: () => window.print() }, 'Imprimer'))),
  ];

  if (erreursDonnees.length) {
    blocs.push(el('div', { class: 'pas-impression' },
      blocErreurs('Tes produits ou tes alias contiennent des erreurs (onglet Catalogue) :', erreursDonnees)));
  }

  blocs.push(el('section', { class: 'carte' },
    el('h2', {}, `À commander — ${liste.aCommander.length}`),
    liste.aCommander.length
      ? el('ul', { class: 'items' }, liste.aCommander.map(itemCommande))
      : el('p', { class: 'vide' }, 'Aucun ingrédient ne correspond encore à tes produits La Fourche.')));

  blocs.push(el('section', { class: 'carte' },
    el('h2', {}, `À chercher sur La Fourche — ${liste.aChercher.length}`),
    liste.aChercher.length
      ? el('ul', { class: 'items' }, liste.aChercher.map(itemAChercher))
      : el('p', { class: 'vide' }, 'Tout est déjà dans tes produits.')));

  if (liste.aVerifier.length) {
    blocs.push(el('section', { class: 'carte' },
      el('h2', {}, `À vérifier — ${liste.aVerifier.length}`),
      el('ul', { class: 'verifier' }, liste.aVerifier.map((v) => el('li', {}, v)))));
  }

  if (liste.dejaLa.length) {
    blocs.push(el('section', { class: 'carte' },
      el('details', {},
        el('summary', {}, `Déjà à la maison — ${liste.dejaLa.length}`),
        el('ul', { class: 'items' }, liste.dejaLa.map((i) => el('li', { class: 'item' },
          el('div', { class: 'item-corps' },
            el('div', { class: 'item-ligne' },
              el('span', { class: 'item-nom' }, i.nom),
              el('span', { class: 'item-besoin' }, `${formatBesoins(i.besoins, i.sansQuantite)} — ${i.stock}`)),
            origines(i))))))));
  }
  return blocs;
}

async function copier(texte, message) {
  try {
    await navigator.clipboard.writeText(texte);
    toast(message);
  } catch {
    const zone = el('textarea', { value: texte });
    document.body.append(zone);
    zone.select();
    const ok = document.execCommand('copy');
    zone.remove();
    toast(ok ? message : 'Copie impossible dans ce navigateur.');
  }
}

function ajouterProduitVide(nom) {
  etat.catalogue.push({ id: nouvelId(), ingredient: nom, produit: '', lien: '', format: '' });
  sauver();
  allerA('catalogue');
  const ligne = $app.querySelector(`[data-id="${etat.catalogue[etat.catalogue.length - 1].id}"]`);
  ligne?.scrollIntoView({ block: 'center' });
  ligne?.querySelector('.champ-lien')?.focus();
  toast(`« ${nom} » ajouté à tes produits : colle son lien La Fourche.`);
}

function ajouterStock(nom) {
  etat.stock.push({ id: nouvelId(), ingredient: nom, quantite: '' });
  sauver();
  afficher();
  toast(`« ${nom} » ajouté à « Déjà à la maison ».`);
}

// ── Vue : catalogue ───────────────────────────────────────────────────

// Ligne de tableau éditable. colonnes : [{ cle, placeholder, label, type }]
function ligneEditable(objet, colonnes, { classe, surChangement, surSuppression }) {
  const ligne = el('div', { class: classe, 'data-id': objet.id });
  for (const c of colonnes) {
    const input = el('input', {
      id: `${c.cle}-${objet.id}`,
      type: c.type || 'text',
      value: objet[c.cle] || '',
      placeholder: c.placeholder,
      'aria-label': c.label,
      class: `champ-${c.cle}`,
      oninput: (e) => {
        objet[c.cle] = e.target.value.trim();
        if (c.valider) e.target.classList.toggle('invalide', !c.valider(objet[c.cle]));
        sauver();
        surChangement?.();
      },
    });
    if (c.valider) input.classList.toggle('invalide', !c.valider(objet[c.cle] || ''));
    ligne.append(input);
  }
  ligne.append(el('button', {
    type: 'button',
    class: 'bouton-icone',
    title: 'Supprimer la ligne',
    'aria-label': 'Supprimer la ligne',
    onclick: surSuppression,
  }, '✕'));
  return ligne;
}

function sectionStock() {
  const $lignes = el('div', { class: 'tableau-lignes' });
  const colonnes = [
    { cle: 'ingredient', label: 'Ingrédient', placeholder: 'ingrédient (ex. riz basmati)' },
    {
      cle: 'quantite',
      label: 'Quantité',
      placeholder: 'quantité (vide = assez)',
      valider: (v) => !v || Boolean(lireFormat(v)),
    },
  ];
  const remplir = () => {
    $lignes.replaceChildren(...etat.stock.map((s, i) => ligneEditable(s, colonnes, {
      classe: 'stock-ligne',
      surSuppression: () => { etat.stock.splice(i, 1); sauver(); remplir(); },
    })));
  };
  remplir();
  return el('section', { class: 'carte' },
    el('h2', {}, 'Déjà à la maison'),
    el('p', { class: 'aide' },
      'Ce que tu as déjà. Sans quantité, l\'ingrédient est considéré comme suffisant et ne sera pas commandé. Avec une quantité (500 g, 1 L, 6), elle est déduite du besoin.'),
    el('div', { class: 'stock-entete', 'aria-hidden': 'true' }, el('span', {}, 'Ingrédient'), el('span', {}, 'Quantité'), el('span', {})),
    $lignes,
    el('div', { class: 'barre' },
      el('button', {
        type: 'button',
        class: 'bouton',
        onclick: () => {
          etat.stock.push({ id: nouvelId(), ingredient: '', quantite: '' });
          sauver();
          remplir();
          $lignes.lastElementChild?.querySelector('input')?.focus();
        },
      }, '+ Ingrédient')));
}

function sectionProduits() {
  const $erreurs = el('div');
  const $titre = el('h2');
  const $lignes = el('div', { class: 'tableau-lignes' });
  const $etat = el('p', { class: 'aide', 'aria-live': 'polite' });

  const majErreurs = () => {
    const n = etat.catalogue.filter((e) => e.ingredient).length;
    $titre.textContent = `Mes produits La Fourche — ${n}`;
    const { erreurs } = validerCatalogue(etat.catalogue);
    $erreurs.replaceChildren(...[blocErreurs('Import :', erreursImport), blocErreurs('À corriger :', erreurs)].filter(Boolean));
  };

  const colonnes = [
    { cle: 'lien', label: 'Lien', placeholder: `${PREFIXE_LIEN}products/…`, type: 'url', valider: (v) => !v || lienValide(v) },
    { cle: 'ingredient', label: 'Ingrédient', placeholder: 'ingrédient' },
    { cle: 'produit', label: 'Produit', placeholder: 'nom du produit' },
    { cle: 'format', label: 'Format', placeholder: '500 g', valider: (v) => !v || Boolean(lireFormat(v)) },
  ];
  const remplir = () => {
    $lignes.replaceChildren(...etat.catalogue.map((p, i) => {
      const ligne = ligneEditable(p, colonnes, {
        classe: 'cat-ligne',
        surChangement: majErreurs,
        surSuppression: () => { etat.catalogue.splice(i, 1); sauver(); remplir(); majErreurs(); },
      });
      ligne.dataset.recherche = `${p.ingredient} ${p.produit} ${p.lien}`.toLowerCase();
      return ligne;
    }));
  };
  remplir();
  majErreurs();

  const $filtre = el('input', {
    id: 'filtre-produits',
    type: 'search',
    placeholder: 'Filtrer mes produits…',
    'aria-label': 'Filtrer mes produits',
    oninput: () => {
      const q = $filtre.value.trim().toLowerCase();
      for (const ligne of $lignes.children) ligne.hidden = Boolean(q) && !ligne.dataset.recherche.includes(q);
    },
  });

  // Coller des liens : une ligne par lien, rempli d'après l'adresse, puis par Claude.
  const $liens = el('textarea', {
    id: 'liens-a-ajouter',
    class: 'code liens',
    placeholder: 'https://lafourche.fr/products/la-fourche-pois-chiches-bio-0-265kg\nhttps://lafourche.fr/products/…',
    'aria-label': 'Liens La Fourche à ajouter',
  });
  const $ajouter = el('button', {
    type: 'button',
    class: 'bouton principal',
    onclick: async () => {
      const urls = $liens.value.split(/[\s,;]+/).filter(Boolean);
      const dejaLa = new Set(etat.catalogue.map((p) => p.lien));
      const devinettes = [];
      const refuses = [];
      for (const u of urls) {
        const d = devinerDepuisLien(u);
        if (!d) refuses.push(u);
        else if (!dejaLa.has(d.lien)) { dejaLa.add(d.lien); devinettes.push(d); }
      }
      if (!devinettes.length) {
        $etat.textContent = refuses.length
          ? `Aucun lien de fiche produit reconnu. Un lien doit ressembler à ${PREFIXE_LIEN}products/…`
          : 'Ces produits sont déjà dans ton tableau.';
        return;
      }
      let produits = devinettes;
      if (claudeSample) {
        $ajouter.disabled = true;
        $ajouter.textContent = 'Claude lit les liens…';
        try {
          const reponse = await claudeSample.json(consigneProduits(devinettes, nomsConnus()), { modelTier: 'quick' });
          produits = produitsDepuisReponse(reponse, devinettes);
        } catch (e) {
          toast(`${e?.code ? messageClaude(e) : 'Réponse inutilisable.'} Les noms ont été déduits de l'adresse.`);
        } finally {
          $ajouter.disabled = false;
          $ajouter.textContent = 'Ajouter ces liens';
        }
      }
      for (const p of produits) etat.catalogue.push({ id: nouvelId(), ...p });
      $liens.value = '';
      sauver();
      remplir();
      majErreurs();
      $etat.textContent = `${produits.length} produit(s) ajouté(s). Vérifie la colonne « ingrédient » : c'est elle qui fait le lien avec tes recettes.${refuses.length ? ` ${refuses.length} lien(s) non reconnu(s) ignoré(s).` : ''}`;
    },
  }, 'Ajouter ces liens');

  const $fichier = el('input', {
    type: 'file',
    accept: '.csv,text/csv',
    hidden: true,
    onchange: async (e) => {
      const f = e.target.files[0];
      e.target.value = '';
      if (!f) return;
      const { entrees, erreurs } = lireCatalogue(await f.text());
      erreursImport = erreurs;
      const liens = new Set(etat.catalogue.map((p) => p.lien).filter(Boolean));
      const nouveaux = entrees.filter((p) => !p.lien || !liens.has(p.lien));
      for (const p of nouveaux) etat.catalogue.push({ id: nouvelId(), ...p });
      sauver();
      remplir();
      majErreurs();
      toast(`${nouveaux.length} produit(s) importé(s).`);
    },
  });

  const exporter = async () => {
    const csv = `﻿${catalogueEnCSV(validerCatalogue(etat.catalogue).entrees)}`;
    if (DANS_CLAUDE) {
      if (!claudeDownloads) { copier(csv.slice(1), 'CSV copié.'); return; }
      try {
        await claudeDownloads.save({ filename: 'mes-produits-lafourche.csv', data: csv });
      } catch (e) {
        if (e?.code !== 'cancelled') copier(csv.slice(1), 'Téléchargement impossible ici : CSV copié à la place.');
      }
      return;
    }
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = el('a', { href: url, download: 'mes-produits-lafourche.csv' });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return el('section', { class: 'carte' },
    $titre,
    el('p', { class: 'aide' },
      'Colle les liens des produits que tu as déjà commandés (un par ligne, depuis ton navigateur ou tes mails de commande). Le nom, le format et l\'ingrédient sont remplis automatiquement, tu peux les corriger.'),
    $liens,
    el('div', { class: 'barre' }, $ajouter),
    $etat,
    $erreurs,
    $filtre,
    el('div', { class: 'cat-entete', 'aria-hidden': 'true' },
      el('span', {}, 'Lien'), el('span', {}, 'Ingrédient'), el('span', {}, 'Produit'), el('span', {}, 'Format'), el('span', {})),
    $lignes,
    el('div', { class: 'barre' },
      el('button', {
        type: 'button',
        class: 'bouton',
        onclick: () => {
          etat.catalogue.push({ id: nouvelId(), ingredient: '', produit: '', lien: '', format: '' });
          sauver();
          remplir();
          majErreurs();
          $lignes.lastElementChild?.querySelector('input')?.focus();
        },
      }, '+ Ligne vide'),
      el('span', { class: 'espace' }),
      el('button', { type: 'button', class: 'bouton', onclick: () => $fichier.click() }, 'Importer CSV'),
      el('button', { type: 'button', class: 'bouton', onclick: exporter }, 'Exporter CSV'),
      $fichier));
}

function sectionAlias() {
  const $erreurs = el('div', {}, blocErreurs('Alias :', lireAlias(etat.alias || 'variante;ingredient\n').erreurs));
  return el('section', { class: 'carte' },
    el('details', {},
      el('summary', {}, 'Réglage avancé : alias'),
      el('div', { class: 'details-corps' },
        el('p', { class: 'aide' },
          'Pour regrouper les variantes d\'un même ingrédient. Format : variante;ingredient, une par ligne après l\'en-tête. Les pluriels simples sont gérés automatiquement.'),
        el('textarea', {
          id: 'alias',
          class: 'code',
          value: etat.alias,
          spellcheck: false,
          'aria-label': 'Alias',
          oninput: (e) => {
            etat.alias = e.target.value;
            sauver();
            $erreurs.replaceChildren(...[blocErreurs('Alias :', lireAlias(etat.alias || 'variante;ingredient\n').erreurs)].filter(Boolean));
          },
        }),
        $erreurs)));
}

function vueCatalogue() {
  return [sectionProduits(), sectionStock(), sectionAlias()];
}

initialiser();
