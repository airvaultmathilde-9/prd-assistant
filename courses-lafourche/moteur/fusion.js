// Regroupement des ingrédients et addition des quantités compatibles.

// entrees : [{ cle, nom, quantite, unite, recette, original }]
// Renvoie [{ cle, nom, besoins: [{ quantite, unite }], sansQuantite, origines }],
// trié par nom.
export function fusionner(entrees) {
  const groupes = new Map();
  for (const e of entrees) {
    if (!groupes.has(e.cle)) {
      groupes.set(e.cle, { cle: e.cle, nom: e.nom, parUnite: new Map(), sansQuantite: false, origines: [] });
    }
    const g = groupes.get(e.cle);
    if (e.quantite === null || e.quantite === undefined) g.sansQuantite = true;
    else g.parUnite.set(e.unite, (g.parUnite.get(e.unite) || 0) + e.quantite);
    g.origines.push({ recette: e.recette, original: e.original });
  }
  return [...groupes.values()]
    .map(({ parUnite, ...g }) => ({
      ...g,
      besoins: [...parUnite].map(([unite, quantite]) => ({ quantite, unite })),
    }))
    .sort((a, b) => a.nom.localeCompare(b.nom, 'fr'));
}
