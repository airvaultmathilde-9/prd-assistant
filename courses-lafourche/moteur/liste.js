// Assemble la liste de courses à partir des recettes et des données perso.

import { extraireLignes } from './extraction.js';
import { analyserLigne } from './analyse.js';
import { cle, resoudre } from './normalisation.js';
import { fusionner } from './fusion.js';
import { lienRecherche, nombreDeProduits } from './catalogue.js';
import { formatQuantite, lireFormat } from './unites.js';

export function formatBesoins(besoins, sansQuantite) {
  const parts = besoins.map((b) => formatQuantite(b.quantite, b.unite));
  if (sansQuantite) parts.push(parts.length ? 'quantité non précisée en plus' : 'quantité non précisée');
  return parts.join(' + ');
}

// Déduit le stock d'un ingrédient. Renvoie { besoins, couvert, note, incomparable }.
function deduireStock(item, enStock) {
  const stock = lireFormat(enStock.quantite);
  if (!enStock.quantite) return { besoins: item.besoins, couvert: true, note: 'en stock' };
  const note = `${enStock.quantite} en stock`;
  if (!item.besoins.length) return { besoins: [], couvert: true, note };
  if (!stock) return { besoins: item.besoins, couvert: false, incomparable: true };
  const besoin = item.besoins.find((b) => b.unite === stock.unite);
  if (!besoin) return { besoins: item.besoins, couvert: false, incomparable: true };
  const reste = besoin.quantite - stock.quantite;
  const besoins = item.besoins
    .map((b) => (b === besoin ? { ...b, quantite: reste } : b))
    .filter((b) => b.quantite > 1e-9);
  const deduit = `${formatQuantite(stock.quantite, stock.unite)} en stock`;
  return { besoins, couvert: !besoins.length && !item.sansQuantite, note: deduit };
}

// recettes : [{ nom, texte }] ; catalogue : entrées validées ;
// alias : Map(cle -> nom) ; stock : [{ ingredient, quantite }] (quantité
// vide = assez à la maison) ; placard : [nom] (ancien format, sans quantité).
export function genererListe({ recettes, catalogue = [], alias = new Map(), stock = [], placard = [] }) {
  const parCle = new Map(catalogue.map((e) => [cle(e.ingredient), e]));
  const stockParCle = new Map();
  for (const s of [...placard.map((p) => ({ ingredient: p, quantite: '' })), ...stock]) {
    if ((s.ingredient || '').trim()) stockParCle.set(cle(s.ingredient), s);
  }
  const connus = new Set([...parCle.keys(), ...stockParCle.keys()]);
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
  const dejaLa = [];
  for (const brut of fusionner(entrees)) {
    let item = brut;
    if (item.besoins.length > 1) {
      aVerifier.push(`${item.nom} : ${formatBesoins(item.besoins, false)} — unités non additionnables.`);
    }
    const enStock = stockParCle.get(item.cle);
    if (enStock) {
      const d = deduireStock(item, enStock);
      if (d.incomparable) {
        aVerifier.push(`${item.nom} : stock « ${enStock.quantite} » non comparable au besoin (${formatBesoins(item.besoins, item.sansQuantite)}), rien n'a été déduit.`);
      } else if (d.couvert) {
        dejaLa.push({ ...item, stock: d.note });
        continue;
      } else {
        item = { ...item, besoins: d.besoins, stock: d.note };
      }
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

  return { recettes: nomsRecettes, aCommander, aChercher, aVerifier, dejaLa };
}
