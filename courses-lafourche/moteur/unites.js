// Table des unités reconnues, conversions et affichage des quantités.
// Familles additionnables : g (masses), ml (volumes), cas, cac, piece,
// et une famille par contenant (boite, gousse, botte…).

export const sansAccents = (texte) =>
  texte.normalize('NFD').replace(/[̀-ͯ]/g, '').normalize('NFC');

// [motif sur texte minuscule sans accents, clé de famille, facteur vers la base]
const MOTIFS = [
  [/^(?:cuilleree?s?|cuilleres?|cuillers?|cuill?\.?|c)\.?\s*a\.?\s*(?:soupe|s)\b\.?/, 'cas', 1],
  [/^(?:cuilleree?s?|cuilleres?|cuillers?|cuill?\.?|c)\.?\s*a\.?\s*(?:cafe|c)\b\.?/, 'cac', 1],
  [/^(?:cs|tbsp)\b\.?/, 'cas', 1],
  [/^(?:cc|tsp)\b\.?/, 'cac', 1],
  [/^(?:kilogrammes?|kilos?|kgs?)\b\.?/, 'g', 1000],
  [/^(?:milligrammes?|mg)\b\.?/, 'g', 0.001],
  [/^(?:grammes?|grs?|g)\b\.?/, 'g', 1],
  [/^(?:millilitres?|ml)\b\.?/, 'ml', 1],
  [/^(?:centilitres?|cl)\b\.?/, 'ml', 10],
  [/^(?:decilitres?|dl)\b\.?/, 'ml', 100],
  [/^(?:litres?|l)\b(?!['’])\.?/, 'ml', 1000],
];

// Contenants et unités « comptées » : [clé, singulier, pluriel]
const CONTENANTS = [
  ['boite', 'boîte', 'boîtes'],
  ['bocal', 'bocal', 'bocaux'],
  ['botte', 'botte', 'bottes'],
  ['bouquet', 'bouquet', 'bouquets'],
  ['branche', 'branche', 'branches'],
  ['brin', 'brin', 'brins'],
  ['brique', 'brique', 'briques'],
  ['barquette', 'barquette', 'barquettes'],
  ['cube', 'cube', 'cubes'],
  ['feuille', 'feuille', 'feuilles'],
  ['filet', 'filet', 'filets'],
  ['gousse', 'gousse', 'gousses'],
  ['morceau', 'morceau', 'morceaux'],
  ['noix', 'noix', 'noix'],
  ['paquet', 'paquet', 'paquets'],
  ['pincee', 'pincée', 'pincées'],
  ['poignee', 'poignée', 'poignées'],
  ['pot', 'pot', 'pots'],
  ['rouleau', 'rouleau', 'rouleaux'],
  ['sachet', 'sachet', 'sachets'],
  ['tasse', 'tasse', 'tasses'],
  ['tige', 'tige', 'tiges'],
  ['tranche', 'tranche', 'tranches'],
  ['verre', 'verre', 'verres'],
];

const NOMS = {
  g: ['g', 'g'],
  ml: ['ml', 'ml'],
  cas: ['c. à soupe', 'c. à soupe'],
  cac: ['c. à café', 'c. à café'],
  piece: ['pièce', 'pièces'],
};
for (const [cle, sing, plur] of CONTENANTS) {
  NOMS[cle] = [sing, plur];
  const variantes = new Set([sing, plur].map(sansAccents));
  const alternance = [...variantes].sort((a, b) => b.length - a.length).join('|');
  MOTIFS.push([new RegExp(`^(?:${alternance})\\b`), cle, 1]);
}

const ADJECTIFS_UNITE = /^(?:belles?|beaux?|bonnes?|bons?|grosses?|gros|petites?|petits?|grandes?|grands?)\s+/;

// Cherche une unité au début du texte. Renvoie { unite, facteur, longueur }
// (longueur = nombre de caractères consommés dans le texte d'origine) ou null.
export function lireUnite(texte) {
  const brut = sansAccents(texte.toLowerCase());
  let decalage = 0;
  let essai = brut;
  const adj = brut.match(ADJECTIFS_UNITE);
  for (const avecAdjectif of adj ? [true, false] : [false]) {
    decalage = avecAdjectif ? adj[0].length : 0;
    essai = brut.slice(decalage);
    for (const [motif, unite, facteur] of MOTIFS) {
      const m = essai.match(motif);
      if (m) return { unite, facteur, longueur: decalage + m[0].length };
    }
  }
  return null;
}

// « 500 g », « 1 L », « 6 pièces », « 0,265 kg » -> { quantite, unite } en base.
export function lireFormat(texte) {
  if (!texte) return null;
  const m = texte.trim().match(/^(\d+(?:[.,]\d+)?)\s*(.*)$/);
  if (!m) return null;
  const quantite = parseFloat(m[1].replace(',', '.'));
  const reste = m[2].trim();
  if (!reste || /^(?:pieces?|pièces?|pcs?|unites?|unités?|x)$/i.test(reste)) {
    return { quantite, unite: 'piece' };
  }
  const u = lireUnite(reste);
  if (!u || reste.slice(u.longueur).trim()) return null;
  return { quantite: quantite * u.facteur, unite: u.unite };
}

export function formatNombre(n) {
  const arrondi = Math.round(n * 100) / 100;
  return String(arrondi).replace('.', ',');
}

// Affichage d'une quantité exprimée dans l'unité de base de sa famille.
export function formatQuantite(quantite, unite) {
  if (unite === 'g' && quantite >= 1000) return `${formatNombre(quantite / 1000)} kg`;
  if (unite === 'ml' && quantite >= 1000) return `${formatNombre(quantite / 1000)} L`;
  const noms = NOMS[unite] || [unite, unite];
  const nom = quantite > 1 ? noms[1] : noms[0];
  return `${formatNombre(quantite)} ${nom}`;
}

export function nomUnite(unite) {
  return (NOMS[unite] || [unite])[0];
}
