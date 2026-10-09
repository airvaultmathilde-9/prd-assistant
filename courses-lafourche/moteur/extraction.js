// Repère les lignes d'ingrédients dans le texte libre d'une recette.

import { sansAccents } from './unites.js';

const TITRE_INGREDIENTS = /^(?:les\s+)?ingredients?\b/;
const TITRE_FIN = /^(?:preparations?|etapes?|instructions?|methode|realisation|deroule|recette|ustensiles?|materiel|cuisson|astuces?|conseils?|progression|la recette)\b/;
const PUCE = /^\s*[-•*·▪◦–—✓✔]\s*/;
const PORTIONS = /^pour\s+\d+\s*(?:personnes?|pers\.?|parts?|portions?|couverts?)\b/;

const prepare = (ligne) => sansAccents(ligne.trim().toLowerCase()).replace(PUCE, '');

// Une ligne à ignorer dans une section ingrédients : vide, sous-titre
// (« Pour la sauce : »), nombre de portions.
function ignorable(ligne) {
  const t = prepare(ligne);
  if (!t) return true;
  if (PORTIONS.test(t)) return true;
  if (/:\s*$/.test(t) && !/\d/.test(t)) return true;
  return false;
}

// Renvoie { lignes: [texte…], avecSection: bool }.
export function extraireLignes(texte) {
  const lignes = texte.replace(/\r\n?/g, '\n').split('\n');
  const trouvees = [];
  let avecSection = false;

  for (let i = 0; i < lignes.length; i++) {
    const t = prepare(lignes[i]);
    if (!TITRE_INGREDIENTS.test(t)) continue;
    // « Ingrédients : 200 g de farine, … » sur la même ligne : rare, on ignore la ligne titre.
    avecSection = true;
    let vides = 0;
    for (i = i + 1; i < lignes.length; i++) {
      const ligne = lignes[i];
      const p = prepare(ligne);
      if (!p) {
        if (++vides >= 2 && trouvees.length) break;
        continue;
      }
      vides = 0;
      if (TITRE_FIN.test(p) && p.length < 40) break;
      if (TITRE_INGREDIENTS.test(p)) { i--; break; }
      if (ignorable(ligne)) continue;
      trouvees.push(ligne.trim());
    }
  }

  if (avecSection) return { lignes: trouvees, avecSection };

  // Pas de titre « Ingrédients » : lignes à puce ou commençant par une quantité,
  // en écartant les étapes numérotées (« 1. Préchauffer… ») et les phrases longues.
  for (const ligne of lignes) {
    const brut = ligne.trim();
    if (!brut || ignorable(brut)) continue;
    if (/^\d+\s*[.)]\s/.test(brut)) continue;
    if (brut.length > 90) continue;
    if (PUCE.test(brut) || /^(?:\d|[½¼¾⅓⅔])/.test(brut)) trouvees.push(brut);
  }
  return { lignes: trouvees, avecSection: false };
}
