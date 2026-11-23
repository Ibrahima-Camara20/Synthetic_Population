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
| `voix.py` | Synthèse vocale ElevenLabs, réplique par réplique (avec cache) |
| `juge.py` | Crédibilité d'une scène : montants inventés, notes d'un juge (modèle) |

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
   modèle, mode, nombre d'agents, température, étiquette, variante, configuration…
7. **Analyses** : qui concède le plus selon sa position, et corrélations entre la
   personnalité (OCEAN) et le résultat de chaque agent.

## La voix (ElevenLabs)

Chaque scène peut être écoutée : bouton **Écouter la scène** au-dessus de la transcription
(onglets Lancer et Scènes jouées). La réplique en cours est surlignée, et la suivante se
prépare pendant la lecture. Survoler le numéro d'une réplique permet de n'écouter qu'elle.
Une fois toute la scène écoutée, **Télécharger le MP3** donne le fichier complet.

- Voix choisie selon le sexe et l'âge de l'agent (`voix.json`), voix « narrateur » pour le syndic.
- Chaque réplique n'est synthétisée qu'une fois : elle est gardée dans `scenes/audio/`
  (réécouter ne consomme pas de crédits).
- La clé n'est jamais saisie dans le labo ni écrite dans un fichier `.py` (le dépôt est public).
  Créez une fois pour toutes `agent/cle_elevenlabs.txt` contenant seulement la clé (`sk_...`) :
  ce fichier est exclu de Git par `.gitignore`. La variable d'environnement `ELEVENLABS_API_KEY`
  reste possible et passe en priorité.

Le voyant « Voix » de la barre latérale dit si la clé et `voix.json` sont trouvés.
« Lire chaque nouvelle scène » lance la lecture automatiquement à la fin d'une scène.

## Scènes à trois agents

En négociation, une scène peut réunir **trois agents** (barre latérale, « Agents par scène ») :
un « pour », un « contre » et, de préférence, un « partagé ». Ils parlent à tour de rôle et
voient le nom de qui parle ; la zone d'accord est l'ensemble des options acceptables pour
**les trois** ; l'accord est conclu quand chacun l'a signalé. Le débat reste à deux.

Pour comparer 2 et 3 agents, une expérience avec une variante « 2 » et une variante « 3 » :
les groupes sont tirés à trois, et la variante à deux garde le « pour » et le « contre » du
même groupe. La comparaison reste appariée.

## Trajectoire des propositions et concessions

Après chaque négociation, le secrétaire de séance (le modèle, sinon des mots-clés) note la
proposition que chaque réplique avance ou défend. Le labo trace la **trajectoire** : coût du
projet par an selon chaque agent, réplique après réplique, avec la zone d'accord, l'arrivée
du syndic et l'accord final. La **concession** d'un agent est le chemin entre sa première
proposition et l'accord, en € par an et en part du budget (un « pour » concède en baissant le
coût, un « contre » en l'augmentant, un « partagé » dans un sens ou dans l'autre).

## Personnalité et résultat (onglet Analyses)

Une ligne par agent et par négociation : ses traits OCEAN, sa position, et ce qu'il en tire
(accord, **marge préservée** = 1 − hausse retenue / plafond secret, concession). Le labo
calcule la corrélation de chaque trait avec chaque résultat, avec son intervalle de confiance
à 95 % (Fisher), et trace le nuage de points correspondant. Prudence : 15 corrélations sont
testées (une ou deux peuvent paraître nettes par hasard), et la position joue aussi.

## Le juge : la scène est-elle crédible ?

- **Chiffres** (toujours, gratuit) : chaque montant en euros cité est comparé aux montants réels
  (à 2 % près) ; un montant qui ne correspond à rien est compté comme inventé.
- **Juge** (case « Faire évaluer par le juge », un appel de plus au modèle) : notes de 1 à 5 de
  fidélité à la fiche (par agent), de cohérence et de naturel, et un commentaire. Un autre
  modèle peut servir de juge (réglages avancés). Une scène peut être évaluée après coup depuis
  « Scènes jouées ». Les évaluations sont rangées dans `scenes/juges.jsonl`.
- Une scène est **valide** si aucun montant n'est inventé et, si elle a été jugée, si la
  fidélité moyenne et la cohérence valent au moins 3. « Accords valides » ne compte que ceux-là.

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
`negociation.py`.r_paire`, `tirer_groupes`). Les hypothèses de négociation (parts des
postes, étalements, marges par défaut, règles « tient à ») sont en tête de
`negociation.py`.

La barre latérale indique les fonctions détectées (✅ / ⬜).
