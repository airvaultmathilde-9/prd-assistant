import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { analyserLigne } from '../moteur/analyse.js';
import { extraireLignes } from '../moteur/extraction.js';
import { cle, resoudre } from '../moteur/normalisation.js';
import { formatQuantite, lireFormat } from '../moteur/unites.js';
import {
  lireCatalogue, lireAlias, lirePlacard, catalogueEnCSV, parserCSV,
  nombreDeProduits, lienRecherche,
} from '../moteur/catalogue.js';
import { genererListe } from '../moteur/liste.js';
import { enMarkdown } from '../moteur/rendu.js';

const un = (ligne) => {
  const r = analyserLigne(ligne);
  assert.equal(r.length, 1, `une seule entrée attendue pour « ${ligne} »`);
  return r[0];
};

test('analyse : quantités, unités et noms', () => {
  const cas = [
    ['- 200 g de lentilles corail', 200, 'g', 'lentilles corail'],
    ['• 2 oignons jaunes', 2, 'piece', 'oignons jaunes'],
    ['1 c. à soupe de curry', 1, 'cas', 'curry'],
    ['3 cuillères à café de cumin', 3, 'cac', 'cumin'],
    ['1 c.à.s d\'huile d\'olive', 1, 'cas', "huile d'olive"],
    ['2 cs de miel', 2, 'cas', 'miel'],
    ['1/2 litre de lait de coco', 500, 'ml', 'lait de coco'],
    ['un demi-litre de lait', 500, 'ml', 'lait'],
    ['1,5 kg de courge butternut', 1500, 'g', 'courge butternut'],
    ['1.5 kg de courge', 1500, 'g', 'courge'],
    ['1 1/2 kg de pommes', 1500, 'g', 'pommes'],
    ['½ citron', 0.5, 'piece', 'citron'],
    ['10 cl de crème', 100, 'ml', 'crème'],
    ['200g de farine', 200, 'g', 'farine'],
    ['2 gousses d\'ail', 2, 'gousse', 'ail'],
    ['une pincée de sel', 1, 'pincee', 'sel'],
    ['Une belle poignée d\'herbes', 1, 'poignee', 'herbes'],
    ['1 cuillère à soupe rase de sucre', 1, 'cas', 'sucre'],
    ['2 oignons, émincés', 2, 'piece', 'oignons'],
    ['Farine : 200 g', 200, 'g', 'Farine'],
    ['Oeufs : 3', 3, 'piece', 'Oeufs'],
    ['pois chiches 265 g', 265, 'g', 'pois chiches'],
    ['3 noix', 3, 'piece', 'noix'],
    ['1 noix de beurre', 1, 'noix', 'beurre'],
  ];
  for (const [ligne, quantite, unite, nom] of cas) {
    const r = un(ligne);
    assert.deepEqual([r.quantite, r.unite, r.nom], [quantite, unite, nom], ligne);
  }
});

test('analyse : boîte avec précision entre parenthèses', () => {
  const r = un('1 boîte de tomates concassées (400 g)');
  assert.equal(r.unite, 'boite');
  assert.equal(r.precision, '400 g');
});

test('analyse : fourchette signalée, maximum retenu', () => {
  const r = un('2 à 3 carottes');
  assert.equal(r.quantite, 3);
  assert.equal(r.fourchette, '2 à 3');
});

test('analyse : sans quantité et lignes multiples', () => {
  assert.deepEqual(analyserLigne('Sel, poivre').map((r) => r.nom), ['Sel', 'poivre']);
  assert.deepEqual(analyserLigne('sel et poivre du moulin').map((r) => r.nom), ['sel', 'poivre du moulin']);
  assert.deepEqual(analyserLigne('persil, ciselé').map((r) => r.nom), ['persil']);
  const q = un('quelques feuilles de basilic');
  assert.equal(q.quantite, null);
  assert.equal(q.nom, 'basilic');
  const deux = analyserLigne('2 carottes et 1 oignon');
  assert.deepEqual(deux.map((r) => [r.quantite, r.nom]), [[2, 'carottes'], [1, 'oignon']]);
});

test('analyse : phrase non comprise signalée une seule fois', () => {
  const r = analyserLigne('Préchauffez le four à 180°C et enfournez le plat pendant 30 minutes');
  assert.deepEqual(r.map((x) => x.erreur), ['non comprise']);
});

test('extraction : section Ingrédients jusqu\'à Préparation', () => {
  const texte = `Curry de lentilles
Pour 4 personnes

Ingrédients
- 200 g de lentilles corail
Pour la sauce :
- 400 ml de lait de coco

Préparation
1. Rincer les lentilles.
2. Ajouter 400 ml d'eau.`;
  const { lignes, avecSection } = extraireLignes(texte);
  assert.equal(avecSection, true);
  assert.deepEqual(lignes, ['- 200 g de lentilles corail', '- 400 ml de lait de coco']);
});

test('extraction : sans titre, puces et nombres, étapes écartées', () => {
  const texte = `Gratin
- 1 courge
2 oignons
1. Couper la courge en dés.`;
  const { lignes, avecSection } = extraireLignes(texte);
  assert.equal(avecSection, false);
  assert.deepEqual(lignes, ['- 1 courge', '2 oignons']);
});

test('normalisation : pluriels, accents, alias, adjectifs', () => {
  assert.equal(cle('Oignons Jaunes'), 'oignon jaune');
  assert.equal(cle('pois chiches'), 'pois chiche');
  assert.equal(cle('Pommes de terre'), 'pomme de terre');
  assert.equal(cle('radis'), 'radis');
  assert.equal(cle('poireaux'), 'poireau');
  assert.equal(cle('Crème fraîche'), 'creme fraiche');
  assert.equal(cle('Œufs'), 'oeuf');
  assert.equal(cle('lentilles corail bio'), 'lentille corail');
  const alias = new Map([[cle('butternut'), 'courge butternut']]);
  assert.deepEqual(resoudre('Butternut', alias), { cle: 'courge butternut', nom: 'courge butternut' });
  assert.equal(resoudre('gros oignons', new Map(), new Set(['oignon'])).cle, 'oignon');
  assert.equal(resoudre('petits pois', new Map(), new Set(['pois chiche'])).cle, 'petit pois');
});

test('unités : formats et affichage', () => {
  assert.deepEqual(lireFormat('500 g'), { quantite: 500, unite: 'g' });
  assert.deepEqual(lireFormat('1 L'), { quantite: 1000, unite: 'ml' });
  assert.deepEqual(lireFormat('0,265 kg'), { quantite: 265, unite: 'g' });
  assert.deepEqual(lireFormat('6 pièces'), { quantite: 6, unite: 'piece' });
  assert.equal(lireFormat('un filet'), null);
  assert.equal(formatQuantite(1500, 'g'), '1,5 kg');
  assert.equal(formatQuantite(500, 'ml'), '500 ml');
  assert.equal(formatQuantite(2, 'boite'), '2 boîtes');
  assert.equal(formatQuantite(1, 'cas'), '1 c. à soupe');
  assert.equal(formatQuantite(3, 'piece'), '3 pièces');
});

test('catalogue : CSV, BOM, guillemets, virgules', () => {
  const csv = '﻿Ingrédient;Produit;Lien;Format\r\npois chiche;"Pois chiches; bio";https://lafourche.fr/products/x;265 g\r\n';
  const { entrees, erreurs } = lireCatalogue(csv);
  assert.deepEqual(erreurs, []);
  assert.equal(entrees[0].produit, 'Pois chiches; bio');
  assert.deepEqual(lireCatalogue(catalogueEnCSV(entrees)).entrees, entrees);
  assert.deepEqual(parserCSV('a,b\n1,2\n'), [['a', 'b'], ['1', '2']]);
});

test('catalogue : liens étrangers, doublons et en-têtes refusés', () => {
  const csv = `ingredient;produit;lien;format
lentille;A;https://exemple.com/x;500 g
lentilles;B;https://lafourche.fr/products/b;500 g
lentille;C;https://lafourche.fr/products/c;500 g
`;
  const { entrees, erreurs } = lireCatalogue(csv);
  assert.deepEqual(entrees.map((e) => e.produit), ['B']);
  assert.equal(erreurs.length, 2);
  assert.equal(lireCatalogue('nom;lien\nx;y\n').erreurs.length, 1);
});

test('catalogue : nombre de produits et lien de recherche', () => {
  assert.equal(nombreDeProduits([{ quantite: 600, unite: 'g' }], '500 g'), 2);
  assert.equal(nombreDeProduits([{ quantite: 500, unite: 'g' }], '500 g'), 1);
  assert.equal(nombreDeProduits([{ quantite: 2, unite: 'cas' }], '40 g'), null);
  assert.equal(nombreDeProduits([], '40 g'), null);
  assert.equal(lienRecherche('courge butternut'), 'https://lafourche.fr/search?query=courge%20butternut');
});

test('alias et placard par défaut se lisent sans erreur', () => {
  const alias = lireAlias(readFileSync(new URL('../donnees/alias-defaut.csv', import.meta.url), 'utf8'));
  assert.deepEqual(alias.erreurs, []);
  assert.ok(alias.alias.size > 5);
  const placard = lirePlacard(readFileSync(new URL('../donnees/placard-defaut.txt', import.meta.url), 'utf8'));
  assert.ok(placard.includes('sel'));
});

test('liste complète : fusion, catalogue, recherche, placard, vérifications', () => {
  const recettes = [
    { nom: 'Curry', texte: `Ingrédients
- 200 g de lentilles corail
- 1 oignon jaune
- 1 boîte de tomates concassées
- Sel, poivre
- Faire revenir les oignons dans une grande poêle avec un filet d'huile d'olive
Préparation
Cuire.` },
    { nom: 'Soupe', texte: `Ingrédients
300 g de lentilles corail
2 oignons jaunes
400 g de tomates concassées
1 kg de butternut` },
    { nom: 'Vide', texte: '' },
  ];
  const { entrees: catalogue } = lireCatalogue(`ingredient;produit;lien;format
lentille corail;Lentilles corail 500 g;https://lafourche.fr/products/lentilles;500 g
oignon jaune;Oignons jaunes 1 kg;https://lafourche.fr/products/oignons;1 kg
`);
  const liste = genererListe({
    recettes,
    catalogue,
    alias: new Map([[cle('butternut'), 'courge butternut']]),
    placard: ['sel', 'poivre'],
  });

  assert.deepEqual(liste.recettes, ['Curry', 'Soupe']);
  const lentilles = liste.aCommander.find((i) => i.nom === 'lentille corail');
  assert.deepEqual(lentilles.besoins, [{ quantite: 500, unite: 'g' }]);
  assert.equal(lentilles.nombre, 1);
  assert.equal(lentilles.origines.length, 2);
  const oignons = liste.aCommander.find((i) => i.nom === 'oignon jaune');
  assert.deepEqual(oignons.besoins, [{ quantite: 3, unite: 'piece' }]);
  assert.equal(oignons.nombre, null);

  assert.deepEqual(liste.aChercher.map((i) => i.nom), ['courge butternut', 'tomate concassée']);
  assert.deepEqual(liste.auPlacard.map((i) => i.nom), ['poivre', 'sel']);
  assert.ok(liste.aVerifier.some((v) => v.includes('tomate concassée') && v.includes('non additionnables')));
  assert.ok(liste.aVerifier.some((v) => v.includes('non comprise')));

  const md = enMarkdown(liste, 'Courses du test');
  assert.match(md, /^# Courses du test/);
  assert.match(md, /\*\*Lentilles corail 500 g\*\* × 1 — besoin : 500 g — \[ouvrir\]\(https:\/\/lafourche\.fr\/products\/lentilles\)/);
  assert.match(md, /courge butternut — besoin : 1 kg — \[rechercher sur La Fourche\]\(https:\/\/lafourche\.fr\/search\?query=courge%20butternut\)/);
  assert.match(md, /Supposés au placard/);
});
