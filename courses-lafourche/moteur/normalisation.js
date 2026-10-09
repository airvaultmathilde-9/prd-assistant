// Normalisation des noms d'ingrédients : minuscules, espaces, pluriels, alias.

import { sansAccents } from './unites.js';

export function nettoyerTexte(texte) {
  return texte
    .normalize('NFC')
    .replace(/[’`]/g, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

// Pluriel simple : on retire le -s ou -x final, sauf pour les mots qui
// s'écrivent pareil au singulier (pois, radis, jus, ananas, noix…).
export function singulierMot(mot) {
  if (mot.length <= 3) return mot;
  const base = sansAccents(mot);
  if (/eaux$/.test(base)) return mot.slice(0, -1);
  if (/oux$/.test(base)) return mot.slice(0, -1);
  if (/s$/.test(base) && !/[siuoa]s$/.test(base)) return mot.slice(0, -1);
  return mot;
}

export function singulier(nom) {
  return nom.split(' ').map(singulierMot).join(' ');
}

// Nom lisible : minuscules, sans « bio », au singulier.
export function nomAffiche(texte) {
  const nom = nettoyerTexte(texte)
    .toLowerCase()
    .replace(/\bbio\b/g, '')
    .replace(/[.;:!]+$/, '')
    .replace(/\s+/g, ' ')
    .trim();
  return singulier(nom);
}

// Clé de correspondance : nom affiché sans accents.
export function cle(texte) {
  return sansAccents(nomAffiche(texte))
    .replace(/œ/g, 'oe')
    .replace(/æ/g, 'ae')
    .replace(/-/g, ' ');
}

const ADJECTIF_TAILLE = /^(?:grosses?|gros|petites?|petits?|belles?|beaux?|beau|grandes?|grands?|bonnes?|bons?)\s+/;

// Associe un nom brut à son ingrédient canonique.
// alias : Map(cle variante -> nom canonique) ; connus : Set de clés connues
// (catalogue, alias, placard). Renvoie { cle, nom }.
export function resoudre(texte, alias = new Map(), connus = new Set()) {
  const essais = [nomAffiche(texte)];
  const sansAdj = essais[0].replace(ADJECTIF_TAILLE, '');
  if (sansAdj !== essais[0]) essais.push(sansAdj);

  for (const nom of essais) {
    const k = cle(nom);
    if (alias.has(k)) {
      const cible = alias.get(k);
      return { cle: cle(cible), nom: nomAffiche(cible) };
    }
    if (connus.has(k)) return { cle: k, nom };
  }
  return { cle: cle(essais[0]), nom: essais[0] };
}
