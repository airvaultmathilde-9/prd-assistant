// Demandes à Claude (génération d'ingrédients, lecture de liens produit) :
// construction des consignes et validation des réponses. Aucun appel ici :
// app.js fait l'appel, ce module reste pur et testable.

import { formatNombre, formatQuantite, lireFormat } from './unites.js';

// Unités que la réponse peut utiliser, et leur écriture comprise par analyse.js.
const UNITES = {
  'g': 'g',
  'kg': 'kg',
  'ml': 'ml',
  'cl': 'cl',
  'l': 'l',
  'c. à soupe': 'c. à soupe',
  'c. à café': 'c. à café',
  'pièce': '',
  'gousse': 'gousses',
  'botte': 'bottes',
  'pincée': 'pincées',
  'boîte': 'boîtes',
  'sachet': 'sachets',
  'brin': 'brins',
  'feuille': 'feuilles',
  'tranche': 'tranches',
};

const texteCourt = (v, max) => (typeof v === 'string' ? v.replace(/\s+/g, ' ').trim().slice(0, max) : '');

export function consigneIngredients({ recette, personnes, nomsConnus = [] }) {
  const connus = nomsConnus.length
    ? `\nQuand un ingrédient correspond à l'un de ces noms, écris-le exactement ainsi : ${nomsConnus.slice(0, 300).join(' ; ')}.`
    : '';
  return `Tu aides à préparer une liste de courses dans une épicerie bio française.
Donne la liste des ingrédients nécessaires pour cette recette, pour ${personnes} personne${personnes > 1 ? 's' : ''}.

Recette : « ${recette} »

Règles :
- Quantités adaptées à ${personnes} personne${personnes > 1 ? 's' : ''}, en unités métriques.
- « unite » vaut exactement l'une de : ${Object.keys(UNITES).join(', ')}. Utilise « pièce » pour ce qui se compte (oignon, œuf, citron).
- « nom » : l'ingrédient seul, au singulier, en minuscules, sans « bio », sans préparation (pas « émincé », « haché »).
- Assaisonnements au goût (sel, poivre) : « quantite » à null.
- N'invente pas d'ingrédients exotiques : une version classique et simple de la recette.${connus}

Réponds uniquement avec ce JSON :
{"titre": "nom court de la recette", "ingredients": [{"quantite": 200, "unite": "g", "nom": "lentille corail"}]}`;
}

// Transforme la réponse JSON en lignes de texte que analyse.js comprend.
// Renvoie { titre, lignes, ignorees } ; lève une erreur si la forme est fausse.
export function lignesDepuisReponse(reponse) {
  if (!reponse || !Array.isArray(reponse.ingredients)) {
    throw new Error('Réponse sans liste « ingredients ».');
  }
  const lignes = [];
  let ignorees = 0;
  for (const i of reponse.ingredients.slice(0, 60)) {
    const nom = texteCourt(i?.nom, 60);
    if (!nom) { ignorees++; continue; }
    const q = typeof i.quantite === 'number' && Number.isFinite(i.quantite) && i.quantite > 0 ? i.quantite : null;
    if (q === null) { lignes.push(`- ${nom}`); continue; }
    const unite = UNITES[texteCourt(i.unite, 20).toLowerCase()];
    if (unite === undefined) { ignorees++; lignes.push(`- ${nom}`); continue; }
    const article = !unite ? '' : /^[aeiouyhéèêœ]/i.test(nom) ? "d'" : 'de ';
    lignes.push(`- ${formatNombre(q)}${unite ? ` ${unite}` : ''} ${article}${nom}`);
  }
  return { titre: texteCourt(reponse.titre, 80), lignes, ignorees };
}

// ── Liens produit La Fourche ──────────────────────────────────────────

const MARQUES = ['la-fourche'];

// Devine produit, ingrédient et format à partir du seul texte de l'URL
// (aucune requête réseau). Renvoie null si ce n'est pas une fiche produit.
export function devinerDepuisLien(url) {
  let chemin;
  try {
    const u = new URL(url.trim());
    if (u.hostname !== 'lafourche.fr' && u.hostname !== 'www.lafourche.fr') return null;
    chemin = u.pathname;
  } catch {
    return null;
  }
  const m = chemin.match(/^\/products\/([a-z0-9-]+)\/?$/i);
  if (!m) return null;
  let slug = m[1].toLowerCase();

  let format = '';
  const f = slug.match(/-(\d+)(?:-(\d+))?(kg|g|ml|cl|l)$/);
  if (f) {
    const nombre = f[2] ? `${f[1]},${f[2]}` : f[1];
    const lu = lireFormat(`${nombre} ${f[3]}`);
    if (lu) format = formatQuantite(lu.quantite, lu.unite);
    slug = slug.slice(0, f.index);
  }
  let mots = slug.split('-').filter(Boolean);
  for (const marque of MARQUES) {
    const mm = marque.split('-');
    if (mm.every((x, k) => mots[k] === x)) mots = mots.slice(mm.length);
  }
  const sansBio = mots.filter((w) => w !== 'bio');
  const nom = sansBio.join(' ');
  const produit = [mots.join(' '), format].filter(Boolean).join(' ');
  return {
    lien: `https://lafourche.fr/products/${m[1]}`,
    produit: produit.charAt(0).toUpperCase() + produit.slice(1),
    ingredient: nom,
    format,
  };
}

export function consigneProduits(lignes, nomsConnus = []) {
  const connus = nomsConnus.length
    ? `\nSi l'ingrédient correspond à l'un de ces noms, écris-le exactement ainsi : ${nomsConnus.slice(0, 300).join(' ; ')}.`
    : '';
  const liste = lignes.map((l, i) => `${i + 1}. ${l.lien}`).join('\n');
  return `Voici des liens de fiches produit de l'épicerie bio La Fourche. Tu ne peux pas les ouvrir : déduis tout du texte de l'adresse.
Pour chacun, donne :
- « ingredient » : l'ingrédient de cuisine générique, au singulier, en minuscules, sans marque ni « bio » (ex. « pois chiche », « lait de coco »).
- « produit » : un nom de produit lisible en français (marque comprise si elle apparaît).
- « format » : le conditionnement s'il apparaît dans l'adresse, écrit « 500 g », « 1 L », « 6 pièces » ; sinon "".${connus}

${liste}

Réponds uniquement avec ce JSON, dans le même ordre :
{"produits": [{"ingredient": "pois chiche", "produit": "Pois chiches bio La Fourche 265 g", "format": "265 g"}]}`;
}

// Fusionne la réponse de Claude avec les devinettes, ligne par ligne.
export function produitsDepuisReponse(reponse, devinettes) {
  const liste = Array.isArray(reponse?.produits) ? reponse.produits : [];
  return devinettes.map((d, i) => {
    const r = liste[i] || {};
    const format = texteCourt(r.format, 20);
    return {
      ...d,
      ingredient: texteCourt(r.ingredient, 60).toLowerCase() || d.ingredient,
      produit: texteCourt(r.produit, 120) || d.produit,
      format: format && lireFormat(format) ? format : d.format,
    };
  });
}
