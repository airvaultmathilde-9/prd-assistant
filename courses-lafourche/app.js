// Interface : onglets, saisie des recettes, liste, catalogue, localStorage.
// Toute la logique métier est dans moteur/ ; ici on ne fait que l'affichage.
// Règle : aucun innerHTML, tout texte utilisateur passe par des nœuds texte.

import { genererListe, formatBesoins } from './moteur/liste.js';
import { enMarkdown, titreListe } from './moteur/rendu.js';
import {
  validerCatalogue, lireCatalogue, catalogueEnCSV, lireAlias, lirePlacard, lienValide, PREFIXE_LIEN,
} from './moteur/catalogue.js';

const CLE_STOCKAGE = 'courses-lafourche:v1';
const ONGLETS = ['recettes', 'liste', 'catalogue'];

const $app = document.getElementById('app');
const $toasts = document.getElementById('toasts');

let etat = null;
let stockageOk = true;
let erreursImport = [];

// ── Stockage ──────────────────────────────────────────────────────────

function nouvelleRecette() {
  return { id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, nom: '', texte: '' };
}

function charger() {
  try {
    const brut = localStorage.getItem(CLE_STOCKAGE);
    return brut ? JSON.parse(brut) : null;
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

async function initialiser() {
  const sauvegarde = charger();
  if (sauvegarde) {
    etat = {
      onglet: 'recettes',
      recettes: [],
      catalogue: [],
      alias: '',
      placard: '',
      coches: {},
      ...sauvegarde,
    };
  } else {
    etat = {
      onglet: 'recettes',
      recettes: [nouvelleRecette()],
      catalogue: [],
      alias: await lireDefaut('donnees/alias-defaut.csv'),
      placard: await lireDefaut('donnees/placard-defaut.txt'),
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
  setTimeout(() => t.remove(), 3500);
}

function blocErreurs(titre, erreurs) {
  if (!erreurs.length) return null;
  return el('div', { class: 'erreurs', role: 'alert' },
    el('strong', {}, titre),
    el('ul', {}, erreurs.map((e) => el('li', {}, e))));
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

// ── Données dérivées ──────────────────────────────────────────────────

function donneesPerso() {
  const catalogue = validerCatalogue(etat.catalogue);
  const alias = lireAlias(etat.alias || 'variante;ingredient\n');
  return {
    catalogue,
    alias,
    placard: lirePlacard(etat.placard || ''),
  };
}

// ── Vue : recettes ────────────────────────────────────────────────────

function vueRecettes() {
  const cartes = etat.recettes.map((r, i) => el('section', { class: 'carte recette' },
    el('div', { class: 'barre' },
      el('input', {
        type: 'text',
        value: r.nom,
        placeholder: `Nom de la recette ${i + 1}`,
        'aria-label': `Nom de la recette ${i + 1}`,
        oninput: (e) => { r.nom = e.target.value; sauver(); },
      }),
      el('button', {
        type: 'button',
        class: 'bouton-icone',
        title: 'Supprimer cette recette',
        'aria-label': 'Supprimer cette recette',
        onclick: () => {
          if ((r.texte.trim() || r.nom.trim()) && !confirm(`Supprimer « ${r.nom || `Recette ${i + 1}`} » ?`)) return;
          etat.recettes.splice(i, 1);
          if (!etat.recettes.length) etat.recettes.push(nouvelleRecette());
          sauver();
          afficher();
        },
      }, '✕')),
    el('textarea', {
      value: r.texte,
      placeholder: 'Colle ici la recette telle quelle (avec sa liste « Ingrédients »)…',
      'aria-label': `Texte de la recette ${i + 1}`,
      oninput: (e) => { r.texte = e.target.value; sauver(); },
    })));

  return [
    el('p', { class: 'aide' },
      'Colle une recette par bloc, copiée depuis le web. La page repère la liste d\'ingrédients, additionne les quantités et les associe à ton catalogue.'),
    ...cartes,
    el('div', { class: 'barre' },
      el('button', {
        type: 'button',
        class: 'bouton',
        onclick: () => {
          etat.recettes.push(nouvelleRecette());
          sauver();
          afficher();
          const zones = $app.querySelectorAll('.recette input');
          zones[zones.length - 1]?.focus();
        },
      }, '+ Recette'),
      el('span', { class: 'espace' }),
      el('button', {
        type: 'button',
        class: 'bouton danger',
        onclick: () => {
          if (!confirm('Vider toutes les recettes et les cases cochées de la semaine ?')) return;
          etat.recettes = [nouvelleRecette()];
          etat.coches = {};
          sauver();
          afficher();
        },
      }, 'Vider la semaine'),
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
      el('span', { class: 'item-besoin' },
        `Besoin : ${formatBesoins(item.besoins, item.sansQuantite)}${item.format ? ` — format ${item.format}` : ''}`),
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
        el('span', { class: 'item-besoin' }, formatBesoins(item.besoins, item.sansQuantite))),
      origines(item),
      el('div', { class: 'item-actions pas-impression' },
        lienExterne(item.lienRecherche, 'Rechercher sur La Fourche ↗'),
        el('button', {
          type: 'button',
          class: 'bouton petit',
          onclick: () => ajouterAuCatalogue(item.nom),
        }, '+ Ajouter au catalogue'))));
  return li;
}

function vueListe() {
  const { catalogue, alias, placard } = donneesPerso();
  const recettes = etat.recettes.filter((r) => r.texte.trim());
  if (!recettes.length) {
    return [el('section', { class: 'carte' },
      el('p', { class: 'vide' }, 'Aucune recette pour l\'instant.'),
      el('div', { class: 'barre' },
        el('button', { type: 'button', class: 'bouton principal', onclick: () => allerA('recettes') }, 'Ajouter des recettes')))];
  }

  const liste = genererListe({ recettes, catalogue: catalogue.entrees, alias: alias.alias, placard });
  const titre = titreListe();
  const erreursDonnees = [...catalogue.erreurs, ...alias.erreurs];

  const blocs = [
    el('section', { class: 'carte' },
      el('h2', { class: 'liste-titre' }, titre),
      el('p', { class: 'aide' }, `Recettes : ${liste.recettes.join(', ')}`),
      el('div', { class: 'barre pas-impression' },
        el('button', {
          type: 'button',
          class: 'bouton',
          onclick: () => copier(enMarkdown(liste, titre)),
        }, 'Copier en Markdown'),
        el('button', { type: 'button', class: 'bouton', onclick: () => window.print() }, 'Imprimer'))),
  ];

  if (erreursDonnees.length) {
    blocs.push(el('div', { class: 'pas-impression' },
      blocErreurs('Ton catalogue ou tes alias contiennent des erreurs (onglet Catalogue) :', erreursDonnees)));
  }

  blocs.push(el('section', { class: 'carte' },
    el('h2', {}, `À commander (catalogue) — ${liste.aCommander.length}`),
    liste.aCommander.length
      ? el('ul', { class: 'items' }, liste.aCommander.map(itemCommande))
      : el('p', { class: 'vide' }, 'Aucun ingrédient trouvé dans ton catalogue.')));

  blocs.push(el('section', { class: 'carte' },
    el('h2', {}, `Absents du catalogue — à chercher — ${liste.aChercher.length}`),
    liste.aChercher.length
      ? el('ul', { class: 'items' }, liste.aChercher.map(itemAChercher))
      : el('p', { class: 'vide' }, 'Tout est au catalogue.')));

  if (liste.aVerifier.length) {
    blocs.push(el('section', { class: 'carte' },
      el('h2', {}, `À vérifier — ${liste.aVerifier.length}`),
      el('ul', { class: 'verifier' }, liste.aVerifier.map((v) => el('li', {}, v)))));
  }

  if (liste.auPlacard.length) {
    blocs.push(el('section', { class: 'carte' },
      el('details', {},
        el('summary', {}, `Supposés au placard — ${liste.auPlacard.length}`),
        el('ul', { class: 'items' }, liste.auPlacard.map((i) => el('li', { class: 'item' },
          el('div', { class: 'item-corps' },
            el('div', { class: 'item-ligne' },
              el('span', { class: 'item-nom' }, i.nom),
              el('span', { class: 'item-besoin' }, formatBesoins(i.besoins, i.sansQuantite))),
            origines(i))))))));
  }
  return blocs;
}

async function copier(texte) {
  try {
    await navigator.clipboard.writeText(texte);
    toast('Liste copiée.');
  } catch {
    const zone = el('textarea', { value: texte });
    document.body.append(zone);
    zone.select();
    const ok = document.execCommand('copy');
    zone.remove();
    toast(ok ? 'Liste copiée.' : 'Copie impossible dans ce navigateur.');
  }
}

function ajouterAuCatalogue(nom) {
  etat.catalogue.push({ ingredient: nom, produit: '', lien: '', format: '' });
  sauver();
  allerA('catalogue');
  const lignes = $app.querySelectorAll('.cat-ligne');
  const derniere = lignes[lignes.length - 1];
  derniere?.scrollIntoView({ block: 'center' });
  derniere?.querySelector('.champ-lien')?.focus();
}

// ── Vue : catalogue ───────────────────────────────────────────────────

function vueCatalogue() {
  const $erreurs = el('div');
  const $titre = el('h2');
  const majErreurs = () => {
    const n = etat.catalogue.filter((e) => e.ingredient).length;
    $titre.textContent = `Catalogue — ${n} produit${n > 1 ? 's' : ''}`;
    const { erreurs } = validerCatalogue(etat.catalogue);
    $erreurs.replaceChildren(...[
      blocErreurs('Import : ', erreursImport),
      blocErreurs('À corriger :', erreurs),
    ].filter(Boolean));
  };

  const champ = (entree, cleChamp, props) => el('input', {
    type: cleChamp === 'lien' ? 'url' : 'text',
    value: entree[cleChamp] || '',
    class: `champ-${cleChamp}${cleChamp === 'lien' && entree.lien && !lienValide(entree.lien) ? ' invalide' : ''}`,
    oninput: (e) => {
      entree[cleChamp] = e.target.value.trim();
      if (cleChamp === 'lien') e.target.classList.toggle('invalide', Boolean(entree.lien) && !lienValide(entree.lien));
      sauver();
      majErreurs();
    },
    ...props,
  });

  const $lignes = el('div', { class: 'cat-lignes' });
  const $filtre = el('input', {
    type: 'search',
    placeholder: 'Filtrer le catalogue…',
    'aria-label': 'Filtrer le catalogue',
    oninput: () => {
      const q = $filtre.value.trim().toLowerCase();
      for (const ligne of $lignes.children) {
        ligne.hidden = Boolean(q) && !ligne.dataset.recherche.includes(q);
      }
    },
  });

  const remplirLignes = () => {
    $lignes.replaceChildren(...etat.catalogue.map((entree, i) => {
      const ligne = el('div', { class: 'cat-ligne' },
        champ(entree, 'ingredient', { placeholder: 'ingrédient', 'aria-label': 'Ingrédient' }),
        champ(entree, 'produit', { placeholder: 'nom du produit', 'aria-label': 'Produit' }),
        champ(entree, 'lien', { placeholder: `${PREFIXE_LIEN}products/…`, 'aria-label': 'Lien' }),
        champ(entree, 'format', { placeholder: '500 g', 'aria-label': 'Format' }),
        el('button', {
          type: 'button',
          class: 'bouton-icone',
          title: 'Supprimer la ligne',
          'aria-label': 'Supprimer la ligne',
          onclick: () => {
            etat.catalogue.splice(i, 1);
            sauver();
            remplirLignes();
            majErreurs();
          },
        }, '✕'));
      ligne.dataset.recherche = `${entree.ingredient} ${entree.produit}`.toLowerCase();
      return ligne;
    }));
  };
  remplirLignes();
  majErreurs();

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
      if (!entrees.length) {
        toast('Aucune ligne importée.');
        majErreurs();
        return;
      }
      if (etat.catalogue.length && !confirm(`Remplacer le catalogue actuel (${etat.catalogue.length} lignes) par ${entrees.length} lignes ?`)) return;
      etat.catalogue = entrees;
      sauver();
      toast(`${entrees.length} lignes importées.`);
      afficher();
    },
  });

  const exporter = () => {
    const blob = new Blob(['﻿', catalogueEnCSV(validerCatalogue(etat.catalogue).entrees)], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = el('a', { href: url, download: 'catalogue-lafourche.csv' });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const { erreurs: erreursAlias } = lireAlias(etat.alias || 'variante;ingredient\n');
  const $erreursAlias = el('div', {}, blocErreurs('Alias :', erreursAlias));

  return [
    el('section', { class: 'carte' },
      $titre,
      el('p', { class: 'aide' },
        'Un ingrédient = un produit La Fourche. Copie le lien depuis la fiche produit dans ton navigateur. Le format (500 g, 1 L, 6 pièces) sert à calculer combien en commander.'),
      el('div', { class: 'barre' },
        el('button', {
          type: 'button',
          class: 'bouton',
          onclick: () => {
            etat.catalogue.push({ ingredient: '', produit: '', lien: '', format: '' });
            sauver();
            remplirLignes();
            $lignes.lastElementChild?.querySelector('input')?.focus();
          },
        }, '+ Ligne'),
        el('button', { type: 'button', class: 'bouton', onclick: () => $fichier.click() }, 'Importer CSV'),
        el('button', { type: 'button', class: 'bouton', onclick: exporter }, 'Exporter CSV'),
        $fichier),
      $filtre,
      $erreurs,
      el('div', { class: 'cat-entete', 'aria-hidden': 'true' },
        el('span', {}, 'Ingrédient'), el('span', {}, 'Produit'), el('span', {}, 'Lien'), el('span', {}, 'Format'), el('span', {})),
      $lignes),

    el('section', { class: 'carte' },
      el('h2', {}, 'Alias'),
      el('p', { class: 'aide' },
        'Pour regrouper les variantes d\'un même ingrédient. Format CSV : variante;ingredient (une par ligne, après l\'en-tête). Les pluriels simples sont gérés automatiquement.'),
      el('textarea', {
        class: 'code',
        value: etat.alias,
        spellcheck: false,
        'aria-label': 'Alias',
        oninput: (e) => {
          etat.alias = e.target.value;
          sauver();
          $erreursAlias.replaceChildren(...[blocErreurs('Alias :', lireAlias(etat.alias || 'variante;ingredient\n').erreurs)].filter(Boolean));
        },
      }),
      $erreursAlias),

    el('section', { class: 'carte' },
      el('h2', {}, 'Placard'),
      el('p', { class: 'aide' },
        'Ce que tu as toujours à la maison : un ingrédient par ligne. Ils sont mis de côté dans « Supposés au placard ».'),
      el('textarea', {
        class: 'code',
        value: etat.placard,
        spellcheck: false,
        'aria-label': 'Placard',
        oninput: (e) => { etat.placard = e.target.value; sauver(); },
      })),
  ];
}

initialiser();
