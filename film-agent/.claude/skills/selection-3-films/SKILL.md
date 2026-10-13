---
name: selection-3-films
description: Méthode pour composer la sélection finale de 3 films (choix sûr, découverte, pari) et rédiger leurs justifications sans spoiler. À charger dès que tu as des candidats et que tu t'apprêtes à recommander des films à Mathilde.
---

# Composer une sélection de 3 films

## 1. Les trois rôles

| Rôle | Ce que c'est | Comment le choisir |
|---|---|---|
| **choix_sur** | Le film qui a le plus de chances de lui plaire ce soir | Très proche de films qu'elle a notés 4 ou 5 : même cinéaste, même acteur·rice, même registre. Note TMDB solide (≥ 6,8 avec assez de votes). Disponible sur ses abonnements si possible. |
| **decouverte** | Un pas de côté qui garde l'essentiel | Garde le cœur de la demande (le ton, le thème) mais change un paramètre : un autre pays, une autre époque, un·e cinéaste qu'elle ne connaît pas. |
| **pari** | Plus audacieux | Un film moins évident ou plus singulier, avec une vraie raison de penser qu'il peut lui plaire (un point commun précis avec un de ses films). Jamais un pari « au hasard ». |

Les trois films doivent être **différents entre eux**, pas trois variantes du même film : varie les cinéastes, les époques ou les tons.

## 2. Vérifications avant de choisir

Pour chacun des 3 films, tu dois avoir :
- son `tmdb_id`, obtenu d'un outil TMDB pendant cette conversation ;
- `check_already_seen` → non vu, sauf si elle accepte le déjà-vu ;
- sa mémoire → ni « pas envie », ni « vu » (voir la section Mémoire du prompt) ;
- `get_watch_options` → disponible chez elle. Un film disponible seulement à l'achat ne peut être qu'un pari, et il faut le signaler.

Respecte ses **préférences mémorisées** (langue, genres à éviter, durée…). Si une préférence t'oblige à écarter un très bon candidat, c'est normal.

## 3. Rédiger « pourquoi » (why)

- 1 ou 2 phrases.
- Cite **au moins un de ses films**, en italique, avec ce qu'elle en a dit : « Tu as trouvé le duo de *Mandibules* "irrésistible" : ici… ».
- Explique le **lien précis** (même cinéaste, même humour, même actrice dans un registre voisin…), pas une généralité.
- Interdit : « un chef-d'œuvre », « acclamé par la critique », « incontournable ». C'est son goût qui compte, pas le consensus.

## 4. Rédiger « l'ambiance » (vibe)

- 1 ou 2 phrases : le point de départ, le ton, le rythme, l'image.
- **Aucun spoiler** : ni rebondissement, ni retournement, ni fin, ni « on découvre que… ». Rien qui se passe après le premier quart du film.
- Ne recopie pas le résumé TMDB : reformule à partir du point de départ seulement.

Exemple correct : « Un homme s'achète un blouson en daim et en devient obsédé : une comédie absurde, sèche et très courte. »
Exemple interdit : « … jusqu'à ce qu'il finisse par tuer tous ceux qui… »

## 5. Si tu n'as pas 3 bons films

Propose-en moins, et dis pourquoi (« un seul film de Dupieux que tu n'as pas vu est disponible »). C'est toujours mieux qu'un film qui ne respecte pas les règles.
