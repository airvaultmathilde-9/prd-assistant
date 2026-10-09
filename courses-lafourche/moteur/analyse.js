// Analyse d'une ligne d'ingrédient : quantité, unité, nom.

import { lireUnite, sansAccents } from './unites.js';
import { nettoyerTexte } from './normalisation.js';

const FRACTIONS = { '½': 0.5, '¼': 0.25, '¾': 0.75, '⅓': 1 / 3, '⅔': 2 / 3 };
const MOTS_NOMBRES = {
  un: 1, une: 1, deux: 2, trois: 3, quatre: 4, cinq: 5, six: 6, sept: 7,
  huit: 8, neuf: 9, dix: 10, onze: 11, douze: 12, quinze: 15, vingt: 20,
};
const NOMBRE = String.raw`\d+(?:[.,]\d+)?`;

const VAGUE = /^(?:un\s+peu\s+d(?:e\s+|')|quelques\s+|un\s+trait\s+d(?:e\s+|')|une?\s+pointe\s+(?:de\s+couteau\s+)?d(?:e\s+|')|du\s+|de\s+la\s+|de\s+l'|des\s+|environ\s+|q\.?s\.?\s+)/;
const ARTICLE = /^(?:de\s+la\s+|de\s+l'\s*|de\s+|d'\s*|du\s+|des\s+)/;
const APRES_UNITE = /^(?:rases?|bombees?|pleines?|bien\s+pleines?)\b\s*/;
const FIN_NOM = /\s*(?:[,;]|\s(?:pour|selon|ou|à\s+volonté|au\s+goût|facultatif|environ)\b).*$/i;
const PREPARATION = /^(?:emincee?s?|hachee?s?|ciselee?s?|coupee?s?|rapee?s?|pelee?s?|epepinee?s?|ecrasee?s?|en\s|finement|grossierement|frais|fraiche|facultatif|selon|a\s+volonte|au\s+gout|pour|du\s+moulin)/;

// Lit un nombre au début du texte. Renvoie { quantite, longueur, fourchette } ou null.
function lireNombre(texte) {
  let m;
  const t = sansAccents(texte.toLowerCase());
  if ((m = t.match(/^(?:une?\s+)?demie?(?:-|\s+)/))) return { quantite: 0.5, longueur: m[0].length };
  if ((m = texte.match(new RegExp(`^(${NOMBRE})\\s*(?:-|–|à|a)\\s*(${NOMBRE})(?!\\s*/)`)))) {
    const n = (s) => parseFloat(s.replace(',', '.'));
    return { quantite: Math.max(n(m[1]), n(m[2])), longueur: m[0].length, fourchette: m[0].trim() };
  }
  if ((m = texte.match(/^(\d+)\s+(\d+)\s*\/\s*(\d+)/))) {
    return { quantite: +m[1] + m[2] / m[3], longueur: m[0].length };
  }
  if ((m = texte.match(/^(\d+)\s*\/\s*(\d+)/))) return { quantite: m[1] / m[2], longueur: m[0].length };
  if ((m = texte.match(new RegExp(`^(${NOMBRE})?\\s*([½¼¾⅓⅔])`)))) {
    return { quantite: (m[1] ? parseFloat(m[1].replace(',', '.')) : 0) + FRACTIONS[m[2]], longueur: m[0].length };
  }
  if ((m = texte.match(new RegExp(`^${NOMBRE}`)))) {
    return { quantite: parseFloat(m[0].replace(',', '.')), longueur: m[0].length };
  }
  if ((m = t.match(/^(une|un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|quinze|vingt)\b\s*/))) {
    return { quantite: MOTS_NOMBRES[m[1]], longueur: m[0].length };
  }
  return null;
}

function nettoyerLigne(ligne) {
  let t = nettoyerTexte(ligne)
    .replace(/^[-•*·▪◦–—✓✔]\s*/, '')
    .replace(/^\d+\s*[.)]\s+(?=\d)/, '');
  const parentheses = [];
  t = t.replace(/\s*\(([^)]*)\)\s*/g, (_, contenu) => {
    parentheses.push(contenu.trim());
    return ' ';
  });
  return { texte: t.replace(/\s+/g, ' ').trim(), parentheses };
}

// Analyse un fragment déjà nettoyé contenant au plus un ingrédient quantifié.
function analyserFragment(texte) {
  let reste = texte;
  let quantite = null;
  let unite = null;
  let fourchette = null;

  const vague = sansAccents(reste.toLowerCase()).match(VAGUE);
  if (vague) reste = reste.slice(vague[0].length);
  else {
    const n = lireNombre(reste);
    if (n) {
      quantite = n.quantite;
      fourchette = n.fourchette || null;
      reste = reste.slice(n.longueur).trim();
      // « un demi-litre », « 1 demi botte »
      const demi = lireNombre(reste);
      if (demi && demi.quantite === 0.5 && /^demi/i.test(reste)) {
        quantite *= 0.5;
        reste = reste.slice(demi.longueur).trim();
      }
    }
  }

  const u = lireUnite(reste);
  if (u) {
    const apres = reste.slice(u.longueur).trim();
    const nomApres = apres.replace(APRES_UNITE, '').replace(ARTICLE, '').trim();
    if (nomApres) {
      unite = u.unite;
      if (quantite !== null) quantite *= u.facteur;
      reste = nomApres;
    }
  }
  if (quantite !== null && !unite) unite = 'piece';
  reste = reste.replace(ARTICLE, '');

  const nom = reste.replace(FIN_NOM, '').replace(/[.:]+$/, '').trim();
  return { quantite, unite, nom, fourchette };
}

function compris(nom) {
  if (!nom || !/\p{L}/u.test(nom)) return false;
  if (/\d/.test(nom)) return false;
  return nom.split(' ').length <= 6;
}

// Réordonne « Farine : 200 g » ou « Farine 200 g » en « 200 g Farine ».
function quantiteEnFin(texte) {
  const m = texte.match(new RegExp(`^([^\\d:]+?)\\s*(?::\\s*|\\s)((?:${NOMBRE}|\\d+\\s*/\\s*\\d+)\\s*[^\\d]{0,20})$`));
  if (!m) return null;
  const droite = m[2].trim();
  const n = lireNombre(droite);
  const resteDroite = droite.slice(n.longueur).trim();
  if (resteDroite && !lireUnite(resteDroite)) return null;
  if (resteDroite && lireUnite(resteDroite).longueur < resteDroite.replace(/[.]$/, '').length) return null;
  return `${droite} ${m[1].trim()}`;
}

// Analyse une ligne d'ingrédient. Renvoie une liste de résultats
// { quantite, unite, nom, original, fourchette, precision } ou un résultat
// { erreur: 'non comprise', original } si la ligne n'est pas exploitable.
export function analyserLigne(ligne) {
  const original = ligne.trim();
  const { texte, parentheses } = nettoyerLigne(ligne);
  const precision = parentheses.find((p) => /\d/.test(p)) || null;
  if (!texte) return [{ erreur: 'ligne vide', original }];
  // Une phrase (étape de préparation, commentaire) plutôt qu'un ingrédient.
  if (texte.split(' ').length > 12) return [{ erreur: 'non comprise', original }];

  let source = texte;
  if (!lireNombre(source) && !sansAccents(source.toLowerCase()).match(VAGUE)) {
    source = quantiteEnFin(source) || source;
  }

  // Plusieurs ingrédients quantifiés sur une ligne : « 2 carottes et 1 oignon ».
  const morceaux = source.split(/\s*,\s+(?=\d)|\s+(?:et|\+)\s+(?=\d)/);
  const resultats = [];
  for (const morceau of morceaux) {
    const r = analyserFragment(morceau);
    if (r.quantite === null) {
      // Sans quantité : « Sel, poivre », « sel et poivre du moulin ».
      const parts = morceau
        .split(/\s*(?:,|;|\bet\b)\s*/)
        .map((p) => p.trim())
        .filter((p) => p && !PREPARATION.test(sansAccents(p.toLowerCase())));
      if (parts.length > 1) {
        for (const p of parts) {
          const sous = analyserFragment(p);
          resultats.push(compris(sous.nom)
            ? { ...sous, original, precision }
            : { erreur: 'non comprise', original });
        }
        continue;
      }
    }
    resultats.push(compris(r.nom) ? { ...r, original, precision } : { erreur: 'non comprise', original });
  }
  // Une seule erreur par ligne, même si elle a été découpée.
  const valides = resultats.filter((r) => !r.erreur);
  return valides.length === resultats.length ? valides : [...valides, { erreur: 'non comprise', original }];
}
