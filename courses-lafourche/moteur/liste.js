// Assemble la liste de courses à partir des recettes et des données perso.

import { extraireLignes } from './extraction.js';
import { analyserLigne } from './analyse.js';
import { cle, resoudre } from './normalisation.js';
import { fusionner } from './fusion.js';
import { lienRecherche, nombreDeProduits } from './catalogue.js';
import { formatQuantite } from './unites.js';

export function formatBesoins(besoins, sansQuantite) {
  const parts = besoins.map((b) => formatQuantite(b.quantite, b.unite));
  if (sansQuantite) parts.push(parts.length ? 'quantité non précisée en plus' : 'quantité non précisée');
  return parts.join(' + ');
}

// recettes : [{ nom, texte }] ; catalogue : entrées validées ;
// alias : Map(cle -> nom) ; placard : [nom].
export function genererListe({ recettes, catalogue = [], alias = new Map(), placard = [] }) {
  const parCle = new Map(catalogue.map((e) => [cle(e.ingredient), e]));
  const placardCles = new Set(placard.map((p) => cle(p)));
  const connus = new Set([...parCle.keys(), ...placardCles]);
  for (const nom of alias.values()) connus.add(cle(nom));

  const aVerifier = [];
  const entrees = [];
  const nomsRecettes = [];

  recettes.forEach((r, i) => {
    const nomRecette = (r.nom || '').trim() || `Recette ${i + 1}`;
    if (!(r.texte || '').trim()) return;
    nomsRecettes.push(nomRecette);
    const { lignes, avecSection } = extraireLignes(r.texte);
    if (!lignes.length) {
      aVerifier.push(`${nomRecette} : aucun ingrédient trouvé (ajoute une ligne « Ingrédients » au-dessus de la liste).`);
      return;
    }
    if (!avecSection) {
      aVerifier.push(`${nomRecette} : pas de titre « Ingrédients », lignes repérées par puces ou nombres — vérifie qu'il ne manque rien.`);
    }
    for (const ligne of lignes) {
      for (const res of analyserLigne(ligne)) {
        if (res.erreur) {
          aVerifier.push(`${nomRecette}, ligne « ${res.original} » : non comprise, à ajouter à la main.`);
          continue;
        }
        if (res.fourchette) {
          aVerifier.push(`${nomRecette}, ligne « ${res.original} » : fourchette ${res.fourchette}, le maximum a été retenu.`);
        }
        const { cle: k, nom } = resoudre(res.nom, alias, connus);
        entrees.push({ cle: k, nom, quantite: res.quantite, unite: res.unite, recette: nomRecette, original: res.original });
      }
    }
  });

  const aCommander = [];
  const aChercher = [];
  const auPlacard = [];
  for (const item of fusionner(entrees)) {
    if (item.besoins.length > 1) {
      aVerifier.push(`${item.nom} : ${formatBesoins(item.besoins, false)} — unités non additionnables.`);
    }
    if (placardCles.has(item.cle)) {
      auPlacard.push(item);
      continue;
    }
    const produit = parCle.get(item.cle);
    if (produit) {
      aCommander.push({
        ...item,
        nom: produit.ingredient,
        produit: produit.produit || produit.ingredient,
        lien: produit.lien,
        format: produit.format,
        nombre: nombreDeProduits(item.besoins, produit.format),
      });
    } else {
      aChercher.push({ ...item, lienRecherche: lienRecherche(item.nom) });
    }
  }

  return { recettes: nomsRecettes, aCommander, aChercher, aVerifier, auPlacard };
}
