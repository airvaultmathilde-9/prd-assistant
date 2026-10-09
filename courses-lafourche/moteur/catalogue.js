// Catalogue perso : lecture/écriture CSV, validation, correspondance,
// nombre de produits à commander, liens de recherche.

import { lireFormat, sansAccents } from './unites.js';
import { cle, nettoyerTexte } from './normalisation.js';

export const URL_RECHERCHE = 'https://lafourche.fr/search?query=';
export const PREFIXE_LIEN = 'https://lafourche.fr/';
export const COLONNES = ['ingredient', 'produit', 'lien', 'format'];

export function lienRecherche(nom) {
  return URL_RECHERCHE + encodeURIComponent(nom);
}

export function lienValide(lien) {
  return typeof lien === 'string' && lien.startsWith(PREFIXE_LIEN) && !/\s/.test(lien);
}

// CSV minimal : guillemets, "" échappés, retours à la ligne CRLF, BOM d'Excel.
// Séparateur détecté sur la première ligne (« ; » de préférence, sinon « , »).
export function parserCSV(texte) {
  const t = texte.replace(/^﻿/, '');
  const premiere = t.split(/\r?\n/, 1)[0];
  const sep = premiere.includes(';') || !premiere.includes(',') ? ';' : ',';
  const lignes = [];
  let ligne = [];
  let champ = '';
  let guillemets = false;
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (guillemets) {
      if (c === '"' && t[i + 1] === '"') { champ += '"'; i++; }
      else if (c === '"') guillemets = false;
      else champ += c;
    } else if (c === '"' && champ === '') guillemets = true;
    else if (c === sep) { ligne.push(champ); champ = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && t[i + 1] === '\n') i++;
      ligne.push(champ); lignes.push(ligne); ligne = []; champ = '';
    } else champ += c;
  }
  if (champ !== '' || ligne.length) { ligne.push(champ); lignes.push(ligne); }
  return lignes.filter((l) => l.some((c) => c.trim() !== ''));
}

export function ecrireCSV(lignes) {
  const echapper = (v) => {
    const s = String(v ?? '');
    return /[";\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return lignes.map((l) => l.map(echapper).join(';')).join('\r\n') + '\r\n';
}

const enTete = (s) => sansAccents(s.trim().toLowerCase());

// Lit un CSV d'après ses en-têtes. Renvoie { objets, erreurs }.
function lireTable(texte, colonnes) {
  const lignes = parserCSV(texte);
  if (!lignes.length) return { objets: [], erreurs: [] };
  const entetes = lignes[0].map(enTete);
  const manquantes = colonnes.filter((c) => !entetes.includes(c));
  if (manquantes.length) {
    return { objets: [], erreurs: [`En-têtes manquants : ${manquantes.join(', ')} (attendus : ${colonnes.join(';')}).`] };
  }
  const objets = lignes.slice(1).map((l, i) => {
    const o = { _ligne: i + 2 };
    for (const c of colonnes) o[c] = nettoyerTexte(l[entetes.indexOf(c)] ?? '');
    return o;
  });
  return { objets, erreurs: [] };
}

// Valide une liste d'entrées { ingredient, produit, lien, format }.
// Renvoie { entrees (valides), erreurs: [texte] }.
export function validerCatalogue(entrees) {
  const erreurs = [];
  const valides = [];
  const vues = new Map();
  entrees.forEach((e, i) => {
    const ou = e._ligne ? `ligne ${e._ligne}` : `ligne ${i + 1}`;
    const ingredient = (e.ingredient || '').trim();
    if (!ingredient) {
      if (e.produit || e.lien) erreurs.push(`${ou} : ingrédient manquant.`);
      return;
    }
    if (e.lien && !lienValide(e.lien)) {
      erreurs.push(`${ou} (${ingredient}) : le lien doit commencer par ${PREFIXE_LIEN} — ligne ignorée.`);
      return;
    }
    const k = cle(ingredient);
    if (vues.has(k)) {
      erreurs.push(`${ou} : « ${ingredient} » est déjà au catalogue (${vues.get(k)}) — doublon ignoré.`);
      return;
    }
    if (e.format && !lireFormat(e.format)) {
      erreurs.push(`${ou} (${ingredient}) : format « ${e.format} » non compris — le nombre de produits ne sera pas calculé.`);
    }
    vues.set(k, ou);
    valides.push({ ingredient, produit: e.produit || '', lien: e.lien || '', format: e.format || '' });
  });
  return { entrees: valides, erreurs };
}

export function lireCatalogue(texte) {
  const { objets, erreurs } = lireTable(texte, COLONNES);
  if (erreurs.length) return { entrees: [], erreurs };
  return validerCatalogue(objets);
}

export function catalogueEnCSV(entrees) {
  return ecrireCSV([COLONNES, ...entrees.map((e) => COLONNES.map((c) => e[c] || ''))]);
}

// Alias : CSV « variante;ingredient ». Renvoie { alias: Map(cle -> nom), erreurs }.
export function lireAlias(texte) {
  const alias = new Map();
  const { objets, erreurs } = lireTable(texte, ['variante', 'ingredient']);
  for (const o of objets) {
    if (!o.variante || !o.ingredient) {
      erreurs.push(`Alias ligne ${o._ligne} : variante ou ingrédient manquant.`);
      continue;
    }
    alias.set(cle(o.variante), o.ingredient);
  }
  return { alias, erreurs };
}

// Placard : un ingrédient par ligne, « # » pour les commentaires.
export function lirePlacard(texte) {
  return texte
    .split(/\r?\n/)
    .map((l) => l.replace(/#.*$/, '').trim())
    .filter(Boolean);
}

// Nombre de produits à commander, ou null si incalculable
// (format absent/incompris, unités différentes, besoin sans quantité).
export function nombreDeProduits(besoins, format) {
  const f = lireFormat(format);
  if (!f || f.quantite <= 0) return null;
  if (besoins.length !== 1 || besoins[0].unite !== f.unite) return null;
  return Math.max(1, Math.ceil(besoins[0].quantite / f.quantite - 1e-9));
}
