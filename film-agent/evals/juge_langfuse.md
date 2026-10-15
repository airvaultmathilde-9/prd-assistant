# Juge Langfuse : consignes à copier-coller

À coller dans Langfuse, dans le prompt de l'évaluateur LLM-as-a-Judge.
Deux variables : `{{input}}` (Input de l'observation racine « recommandation ») et `{{output}}` (son Output).

---

Tu évalues un agent qui recommande des films à Mathilde, pour regarder chez elle ce soir.

Sa demande :
{{input}}

La réponse de l'agent (3 films, chacun avec un rôle « choix sûr / découverte / pari », un « pourquoi »
qui s'appuie sur des films qu'elle a notés, une « ambiance » et où le voir ; ou bien une question) :
{{output}}

Évalue la QUALITÉ GLOBALE de la recommandation, de 0 à 1 :
- 1 : les films correspondent exactement à l'envie ; les trois rôles sont bien tenus (un choix sûr,
  une vraie découverte, un vrai pari) ; chaque « pourquoi » est précis et personnel ; aucune
  révélation d'intrigue ; tous disponibles chez elle (abonnement, gratuit ou location).
- 0,5 : utile mais avec un vrai défaut (un film hors sujet, des rôles interchangeables,
  des justifications génériques, un film seulement à l'achat hors pari).
- 0 : à côté de la demande, ou spoiler, ou réponse vide.
Si l'agent a posé une question : 1 si la demande était vraiment ambiguë et la question courte et utile,
0 si la demande était claire.

Donne d'abord ton raisonnement en 2 phrases, puis la note.
