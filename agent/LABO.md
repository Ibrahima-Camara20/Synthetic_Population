# Labo des agents

Interface pour enchaîner les scènes entre agents et comparer les résultats.


```bash
python serveur.py
```

Le navigateur s'ouvre sur http://localhost:8000 (autre port : `python serveur.py 8080`).


## Fichiers

| Fichier | Rôle |
|---|---|
| `labo.html` | L'interface (Population, Lancer, Scènes jouées, Statistiques), en HTML/CSS/JS  |
| `serveur.py` | Petit serveur local : sert la page et fait tourner les scènes en arrière-plan |
| `adaptateur.py` | **Seul lien avec le code du projet** (`scene.py`, `personas.py`, `llm.py`) |
| `journal.py` | Enregistre chaque scène dans `scenes/journal.jsonl` |
| `stats.py` | Calcule les mesures à partir du journal |


## Onglets

- **Population** : les 500 agents, filtres (revenu, âge, position), fiche, enjeux, marge secrète.
- **Lancer** :
  - une scène : paire automatique ou agents choisis ; la zone d'accord s'affiche avant le lancement et le dialogue en direct ;
  - une série : N scènes d'affilée, graine par graine ou paire fixe.
- **Scènes** : relire chaque scène jouée avec son verdict.
- **Statistiques** :
  - taux d'accord ;
  - accords cohérents avec les marges ;
  - accords sans médiateur ;
  - accords malgré une zone vide (doit rester à 0 %) ;
  - répliques mal formées et durée moyenne.

  Ces mesures se comparent par modèle, température, étiquette ou série. Export CSV possible.

Les réglages de la barre latérale sont mémorisés dans le navigateur. Le modèle se règle dans la barre latérale (test, ollama, openai, anthropic). L'**étiquette** sert à
nommer une variante (ex. « prompt v2 ») pour la comparer ensuite.

## Brancher la version `main` 

L'adaptateur cherche automatiquement les fonctions suivantes dans `scene.py` ou `negociation.py` :

| Rôle | Noms reconnus | Appel |
|---|---|---|
| Zone d'accord | `zone_accord`, `zone_d_accord`, `calculer_zone`, `options_acceptables` | `f(a, b)` → liste d'options (vide = pas d'accord possible) |
| Vérification finale | `verifier_accord`, `accord_coherent`, `verifier_marges`, `respecte_marges` | `f(proposition, a, b)` → bool |
| Marge secrète | `marge`, `marge_secrete`, `calculer_marge` | `f(p)` → dict |

Si les noms ou les arguments diffèrent, il suffit de modifier les listes `NOMS_*` ou les appels
dans `adaptateur.py`.

Pour `jouer_scene` :

- **Valeur renvoyée.** Elle peut renvoyer l'ancien tuple `(dialogue, ea, eb)` ou un dict. Avec un dict, le labo lit les clés `dialogue`, `accord`, `tour_accord`, `proposition`, `mediateur` et `coherent` si elles existent. Sinon, l'accord est détecté par les balises `[ACCORD]` des deux agents.
- **Médiateur.** Si `jouer_scene` accepte un paramètre `mediateur`, la case de la barre latérale l'active ou le désactive.
- **Trois agents.** Si `jouer_scene` accepte un paramètre `agents=[a, b, c]`, le labo permet d'en choisir trois.
- **Affichage en direct.** Le labo capte les lignes `Nom : réplique` que `jouer_scene` imprime quand `verbeux=True`.

La barre latérale indique les fonctions détectées (✅ / ⬜).
