# Partie 2 : scènes entre agents

Des 500 individus de la population synthétique à des personas qui dialoguent.

## Fichiers

| Fichier | Rôle |
|---|---|
| `attributs.json` | Sens donné aux attributs A0 à A11 (**hypothèse**, modifiable) |
| `personas.py` | Décode la population, tire un profil OCEAN, construit les fiches |
| `population_agents.csv` | Les 500 personas : attributs, scores OCEAN, éléments de fiche |
| `scene.py` | Choisit deux copropriétaires opposés et les fait dialoguer |
| `llm.py` | Appel du modèle de langage (API compatible OpenAI, Claude, ou mode test) |
| `voix.py` | Audio de la scène avec ElevenLabs (optionnel) |
|   |   |

## Lancer une scène

```bash
# Partie 2 : scènes entre agents

Des 500 individus de la population synthétique à des personas qui dialoguent.

## Fichiers

| Fichier | Rôle |
|---|---|
| `attributs.json` | Sens donné aux attributs A0 à A11 (**hypothèse**, modifiable) |
| `personas.py` | Décode la population, tire un profil OCEAN, construit les fiches |
| `population_agents.csv` | Les 500 personas : attributs, scores OCEAN, éléments de fiche |
| `scene.py` | Choisit deux copropriétaires opposés et les fait dialoguer |
| `llm.py` | Appel du modèle de langage (API compatible OpenAI, Claude, ou mode test) |
| `voix.py` | Audio de la scène avec ElevenLabs (optionnel) |

## Lancer une scène

```bash
python personas.py                                  # (re)crée population_agents.csv
python scene.py --backend test                      # sans modèle : vérifie la chaîne

# Avec un vrai modèle (une seule des lignes suivantes)
export LLM_API_KEY=...                              # clé de l'API utilisée
python scene.py --backend openai --modele gpt-4o-mini
python scene.py --backend openai --base-url https://api.mistral.ai/v1 --modele mistral-small-latest
python scene.py --backend ollama --modele qwen3.5:4b                     # Ollama en local, sans clé
export ANTHROPIC_API_KEY=...
python scene.py --backend anthropic --modele claude-sonnet-5-5
```

Options utiles : `--graine 3` (autre paire), `--ids 83,396` (paire imposée, le premier
commence), `--tours 14` (longueur), `--temperature 0.9`.

Chaque scène est enregistrée dans `scenes/` : `.md` (fiches + dialogue + contrôles),
`.txt` (une réplique par ligne, prêt pour la synthèse vocale), `.json` (tout).

## La voix (optionnel)

1. Choisir quatre voix dans la bibliothèque ElevenLabs et créer `voix.json` :
   `{"homme_jeune": "...", "homme_age": "...", "femme_jeune": "...", "femme_age": "..."}`
2. `export ELEVENLABS_API_KEY=...`
3. `python scene.py --backend openai --modele gpt-4o-mini --voix` → `scenes/scene_X_Y.mp3`

## Interprétation et règles de cohérence

`attributs.json` donne un sens aux **12 attributs** (hypothèse justifiée par les marginales)
et contient des **règles de cohérence** (ex. « un étudiant n'est pas aisé »). `main.py` les
applique via `regles.py` : les profils incohérents sont retirés des personas autorisées avant
le glouton. Aucun attribut n'est ajouté, et la population respecte à la fois les 729 cellules
et les règles (`python main.py --sans-regles` pour les ignorer). Une règle n'agit que sur des
combinaisons qu'aucune table ne fixe déjà ; si elle contredisait les données, le glouton
échouerait et le signalerait. Optimum prouvé avec les règles : 330 profils distincts (331 sans).

Après avoir relancé `main.py`, relancer `python personas.py` pour mettre les fiches à jour.

## Choix de conception

- **La personnalité est tirée, pas optimisée** (cours, diapositives 22 à 26) : décalages de
  moyenne faibles selon l'âge et le sexe, corrélations entre traits, forte diversité dans
  chaque groupe. Nos individus n'ont ni foyer commun ni réseau social : la personnalité de
  l'un ne dépend pas de celle des autres, donc la séparation population / tirage est justifiée.
- **Les enjeux sont calculés, pas laissés au modèle** : la part des travaux vient de la
  quote-part, et la position (pour / contre / partagé) du poids de cette part dans le revenu.
- **Chaque agent a son propre prompt** et ne voit jamais la fiche de l'autre.
- **Les traits sont décrits par des comportements**, pas par des scores, et les consignes
  interdisent de réciter la fiche : ce sont les défauts observés dans le premier sondage.
- Les noms, métiers, montants et quotes-parts sont des **éléments de mise en scène tirés au
  hasard**, cohérents avec la tranche de revenu et la taille du foyer.
```

Options utiles : `--graine 3` (autre paire), `--ids 83,396` (paire imposée, le premier
commence), `--tours 14` (longueur), `--temperature 0.9`.

Chaque scène est enregistrée dans `scenes/` : `.md` (fiches + dialogue + contrôles),
`.txt` (une réplique par ligne, prêt pour la synthèse vocale), `.json` (tout).

## La voix (optionnel)

1. Choisir quatre voix dans la bibliothèque ElevenLabs et créer `voix.json` :
   `{"homme_jeune": "...", "homme_age": "...", "femme_jeune": "...", "femme_age": "..."}`
2. `export ELEVENLABS_API_KEY=...`
3. `python scene.py --backend openai --modele gpt-4o-mini --voix` → `scenes/scene_X_Y.mp3`

## Interprétation et règles de cohérence

`attributs.json` donne un sens aux **12 attributs** (hypothèse justifiée par les marginales)
et contient des **règles de cohérence** (ex. « un étudiant n'est pas aisé »). `main.py` les
applique via `regles.py` : les profils incohérents sont retirés des personas autorisées avant
le glouton. Aucun attribut n'est ajouté, et la population respecte à la fois les 729 cellules
et les règles (`python main.py --sans-regles` pour les ignorer). Une règle n'agit que sur des
combinaisons qu'aucune table ne fixe déjà ; si elle contredisait les données, le glouton
échouerait et le signalerait. Optimum prouvé avec les règles : 330 profils distincts (331 sans).

Après avoir relancé `main.py`, relancer `python personas.py` pour mettre les fiches à jour.

## Choix de conception

- **La personnalité est tirée, pas optimisée** (cours, diapositives 22 à 26) : décalages de
  moyenne faibles selon l'âge et le sexe, corrélations entre traits, forte diversité dans
  chaque groupe. Nos individus n'ont ni foyer commun ni réseau social : la personnalité de
  l'un ne dépend pas de celle des autres, donc la séparation population / tirage est justifiée.
- **Les enjeux sont calculés, pas laissés au modèle** : la part des travaux vient de la
  quote-part, et la position (pour / contre / partagé) du poids de cette part dans le revenu.
- **Chaque agent a son propre prompt** et ne voit jamais la fiche de l'autre.
- **Les traits sont décrits par des comportements**, pas par des scores, et les consignes
  interdisent de réciter la fiche : ce sont les défauts observés dans le premier sondage.
- Les noms, métiers, montants et quotes-parts sont des **éléments de mise en scène tirés au
  hasard**, cohérents avec la tranche de revenu et la taille du foyer.
```

Options utiles : `--graine 3` (autre paire), `--ids 83,396` (paire imposée, le premier
commence), `--tours 14` (longueur), `--temperature 0.9`.

Chaque scène est enregistrée dans `scenes/` : `.md` (fiches + dialogue + contrôles),
`.txt` (une réplique par ligne, prêt pour la synthèse vocale), `.json` (tout).

## La voix (optionnel)

1. Choisir quatre voix dans la bibliothèque ElevenLabs et créer `voix.json` :
   `{"homme_jeune": "...", "homme_age": "...", "femme_jeune": "...", "femme_age": "..."}`
2. `export ELEVENLABS_API_KEY=...`
3. `python scene.py --backend openai --modele gpt-4o-mini --voix` → `scenes/scene_X_Y.mp3`

## Choix de conception

- **La personnalité est tirée, pas optimisée** (cours, diapositives 22 à 26) : décalages de
  moyenne faibles selon l'âge et le sexe, corrélations entre traits, forte diversité dans
  chaque groupe. Nos individus n'ont ni foyer commun ni réseau social : la personnalité de
  l'un ne dépend pas de celle des autres, donc la séparation population / tirage est justifiée.
- **Les enjeux sont calculés, pas laissés au modèle** : la part des travaux vient de la
  quote-part, et la position (pour / contre / partagé) du poids de cette part dans le revenu.
- **Chaque agent a son propre prompt** et ne voit jamais la fiche de l'autre.
- **Les traits sont décrits par des comportements**, pas par des scores, et les consignes
  interdisent de réciter la fiche : ce sont les défauts observés dans le premier sondage.
- Les noms, métiers, montants et quotes-parts sont des **éléments de mise en scène tirés au
  hasard**, cohérents avec la tranche de revenu et la taille du foyer.
