# Labo des agents

Un banc d'expériences pour étudier **quand et comment deux agents de la population
synthétique convergent vers un accord**, et comparer des réglages (modèle, température,
médiateur, marges, prompts) avec des mesures fiables.

```bash
python serveur.py                    # depuis agent/ ; ouvre http://localhost:8000
python serveur.py 8080               # autre port
```

Rien à installer en plus de pandas et numpy (serveur de la bibliothèque standard).

## Fichiers

| Fichier | Rôle |
|---|---|
| `labo.html` | L'interface (HTML/CSS/JS, sans dépendance) |
| `serveur.py` | Serveur local : sert la page, file d'attente des scènes, API JSON |
| `adaptateur.py` | **Seul lien avec le code du projet** (`scene.py`, `negociation.py`, `personas.py`, `llm.py`) |
| `negociation.py` | Moteur de négociation : postes, marges secrètes, zone d'accord, syndic, extraction et vérification de l'accord |
| `journal.py` | Enregistre chaque scène dans `scenes/journal.jsonl` |
| `stats.py` | Mesures, intervalles de confiance, comparaison appariée des variantes |

## Deux modes de scène

- **Négociation** (défaut) : le projet est découpé en 4 postes votables séparément
  (coûts calés sur le budget du scénario) et payables sur 1, 2 ou 3 ans. Chaque agent
  reçoit une **marge secrète** calculée depuis sa fiche : un plafond de hausse mensuelle
  (en % du revenu, selon sa position) et les postes auxquels il tient. Les agents écrivent
  `[ACCORD]` quand ils acceptent ; le syndic peut proposer un compromis aux 2/3 de la scène.
  L'accord est ensuite extrait (secrétaire de séance = le modèle, sinon mots-clés) puis
  **vérifié** contre les marges des deux agents.
- **Débat** : la scène de `scene.py`, où chacun défend sa position. Pas d'accord mesuré.
  Sert de condition de contrôle.

## Onglets

1. **Population** : les 500 agents, filtres, fiche, enjeux, marge secrète.
2. **Scénario** : situation, budget, **marges de négociation** (plafonds par position),
   objectifs, critère d'éligibilité. Tout se modifie sans toucher au code.
3. **Lancer** : une scène (dialogue en direct, verdict, hausses comparées aux plafonds)
   ou une série de N scènes. Bouton **Arrêter**.
4. **Expériences** : comparer plusieurs **variantes** sur les **mêmes paires d'agents**.
5. **Scènes jouées** : relecture, verdict, **consignes exactes envoyées aux agents**,
   zone d'accord, configuration.
6. **Statistiques** : mesures sur tout le journal, filtrables et comparables par
   modèle, mode, température, étiquette, variante, configuration…

## Les mesures

| Mesure | Question |
|---|---|
| Taux d'accord | Les agents concluent-ils ? |
| Accord si zone | … quand un accord est possible (zone d'accord non vide) ? |
| Dans les marges | L'accord respecte-t-il les limites des deux agents ? |
| Accord / zone vide | Accord alors qu'aucune option n'est acceptable : **doit rester à 0 %** (sinon le modèle « dit oui à tout ») |
| Sans syndic | Accords trouvés avant l'intervention du médiateur |
| Position dans la zone | 0 = option la plus modeste de la zone (avantage « contre »), 1 = la plus ambitieuse (avantage « pour ») |
| Mal formées | Scènes avec un défaut de forme (codes d'attributs, « en tant que », mention d'IA) |

Chaque proportion est donnée avec son **intervalle de confiance à 95 %** (Wilson) et son
effectif : « 60 % [31–83] 6/10 » veut dire qu'avec 10 scènes, on ne peut pas distinguer
60 % de 35 %.

## Expériences

Une expérience tire N paires d'agents (tirage au choix, graine reproductible) ; **chaque
variante joue chaque paire**, éventuellement plusieurs fois, dans un ordre tiré au hasard.
Une variante fixe : mode, backend, modèle, température, nombre de répliques, syndic,
marges. La première variante est la **référence**.

Comme les agents sont les mêmes, la comparaison est **appariée** : le test exact de
McNemar ne compte que les paires où les deux variantes diffèrent (accord avec l'une, pas
avec l'autre). Le labo conclut « différence significative » si p < 0,05, sinon « pas de
différence démontrée ».

Exemples d'expériences utiles :
- **effet du médiateur** : référence avec syndic / variante sans syndic ;
- **effet du modèle** : qwen3.5:4b / un modèle plus gros ;
- **robustesse** : température 0,3 / 0,9 / 1,2 ;
- **contrôle** : tirage « pour / contre » (avec des zones vides) et vérifier
  qu'« accord / zone vide » reste à 0 %.

## File d'attente et reproductibilité

- Un seul travail tourne à la fois (un modèle local ne gagne rien au parallélisme, et les
  durées restent comparables) ; les autres attendent dans la file (barre latérale).
- Chaque ligne du journal garde les agents, les réglages, la configuration complète (avec
  son empreinte `config_id`), les consignes envoyées, l'option retenue et sa méthode
  d'extraction. `pd.read_json("scenes/journal.jsonl", lines=True)` pour l'analyser ailleurs.
- **Étiquette** (barre latérale) : nommer une variante de prompt ou de code (« prompt v2 »)
  pour la comparer ensuite dans Statistiques.

## Modifier le moteur

Les appels au code du projet sont tous dans `adaptateur.py` (`lancer_scene`, `zone`,
`marge`, `choisir_paire`, `tirer_groupes`). Les hypothèses de négociation (parts des
postes, étalements, marges par défaut, règles « tient à ») sont en tête de
`negociation.py`.