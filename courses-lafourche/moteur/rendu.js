// Liste de courses -> Markdown (copie / export).

import { formatBesoins } from './liste.js';

export function titreListe(date = new Date()) {
  return `Courses du ${date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })}`;
}

export function enMarkdown(liste, titre = titreListe()) {
  const l = [`# ${titre}`, ''];
  if (liste.recettes.length) l.push(`Recettes : ${liste.recettes.join(', ')}`, '');

  l.push('## À commander (catalogue)');
  if (!liste.aCommander.length) l.push('_Rien._');
  for (const i of liste.aCommander) {
    const nb = i.nombre ? ` × ${i.nombre}` : ' × ?';
    const lien = i.lien ? ` — [ouvrir](${i.lien})` : '';
    const stock = i.stock ? ` (${i.stock} déduit)` : '';
    l.push(`- [ ] **${i.produit}**${nb} — besoin : ${formatBesoins(i.besoins, i.sansQuantite)}${stock}${lien}`);
  }
  l.push('', '## Absents du catalogue — à chercher');
  if (!liste.aChercher.length) l.push('_Rien._');
  for (const i of liste.aChercher) {
    l.push(`- [ ] ${i.nom} — besoin : ${formatBesoins(i.besoins, i.sansQuantite)} — [rechercher sur La Fourche](${i.lienRecherche})`);
  }
  if (liste.aVerifier.length) {
    l.push('', '## À vérifier');
    for (const v of liste.aVerifier) l.push(`- ${v}`);
  }
  if (liste.dejaLa.length) {
    l.push('', '## Déjà à la maison');
    for (const i of liste.dejaLa) l.push(`- ${i.nom} — besoin : ${formatBesoins(i.besoins, i.sansQuantite)} (${i.stock})`);
  }
  return l.join('\n') + '\n';
}
