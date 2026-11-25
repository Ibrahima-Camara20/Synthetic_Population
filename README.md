# Population synthétique

TER — Ibrahima Camara, encadré par Jean-Charles Régin.

Le projet a deux parties :

1. **Reconstruire une population** de 500 individus qui respecte exactement les 729 cellules
   marginales de 45 tables, avec le moins de profils répétés possible.
2. **Faire jouer ces individus** par des agents conversationnels, et étudier à quelles
   conditions ils parviennent à un accord.

## Organisation

| Dossier | Contenu |
|---|---|
| `donnees/` | Les données de départ : `constraint_cells.csv` (les 729 cellules) et `constraint_scopes.csv` |
| `population/` | **Partie 1** : l'algorithme glouton, la déduplication, les règles de cohérence, le solveur de référence |
| `agent/` | **Partie 2** : les personas, les scènes de négociation, le labo et sa documentation (`LABO.md`) |
| `resultats/` | Ce que produisent les programmes : `population_finale.csv`, `personas_actives.csv` |

Les chemins sont calculés à partir de l'emplacement des fichiers : les scripts se lancent
depuis la racine du projet comme depuis leur propre dossier.

## Partie 1 : construire la population

```bash
python population/main.py                 # construit resultats/population_finale.csv
python population/main.py --sans-regles   # sans les règles de cohérence d'attributs.json
python population/etapes_1_2.py           # chargement, bornes, personas possibles
```

`main.py` enchaîne : chargement des contraintes, bornes `u_x` et `l_x`, filtrage par les
règles de cohérence, glouton par tension, puis deux passes de déduplication (échanges de
blocs, puis destruction-reconstruction). Il affiche à la fin le nombre de profils distincts,
l'entropie et la part de l'optimum atteinte.

**Résultat de référence** : 311 profils distincts, soit 94 % de l'optimum prouvé (330 avec
les règles, 331 sans). L'optimum est obtenu par `population/solveur_reference.py`, qui résout
le même problème avec OR-Tools CP-SAT (`pip install ortools`) — beaucoup plus lent.

Les règles de cohérence (« un étudiant n'est pas aisé », etc.) sont déclarées dans
`agent/attributs.json` et appliquées par `population/regles.py`.

## Partie 2 : les agents

```bash
python agent/personas.py        # (re)crée les fiches à partir de resultats/population_finale.csv
cd agent && python serveur.py   # le labo : http://localhost:8000
```

Tout est documenté dans **`agent/LABO.md`** : les modes de scène, les expériences, les
mesures, la voix et le juge.

Après avoir relancé `population/main.py`, relancer `python agent/personas.py` pour mettre
les fiches à jour.

## Clés d'API

Aucune clé ne doit être écrite dans un fichier `.py` ni poussée sur GitHub.

- **ElevenLabs** (la voix) : créer `agent/cle_elevenlabs.txt` contenant seulement la clé
  (`sk_…`). Le fichier est exclu par `.gitignore`.
- **Modèle de langage** : variable d'environnement `LLM_API_KEY` ou `ANTHROPIC_API_KEY`.
  Avec Ollama en local, aucune clé n'est nécessaire.
