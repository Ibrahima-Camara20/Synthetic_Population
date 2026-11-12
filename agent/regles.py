"""
Population synthétique - Règles de cohérence entre attributs
============================================================

Les règles sont écrites dans attributs.json (dossier agent/ ou agents/), avec
l'interprétation des attributs. Exemple : « un étudiant n'est pas aisé ».

Elles ne créent AUCUN nouvel attribut : elles retirent simplement des personas
actives les profils incohérents, avant le glouton, exactement comme l'étape 2
retire les profils impossibles (u_x = 0). La population produite respecte donc
à la fois les 729 cellules ET les règles.

Une règle n'a d'effet que si aucune table de marginales ne fixe déjà ensemble
ses attributs. Si elle contredit une cellule des données, le glouton échoue :
c'est alors l'interprétation qu'il faut revoir.
"""

import json
import os
import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))


def trouver_fichier():
    for dossier in ("agent", "agents", "."):
        chemin = os.path.join(ICI, dossier, "attributs.json")
        if os.path.exists(chemin):
            return chemin
    return None


def charger_regles(chemin=None):
    """Renvoie [(nom, {attribut: valeur_entiere}), ...] : chaque règle devient
    une combinaison de valeurs interdite."""
    chemin = chemin or trouver_fichier()
    if chemin is None:
        return []
    with open(chemin, encoding="utf-8") as f:
        conf = json.load(f)
    attributs = conf["attributs"]
    regles = []
    for r in conf.get("regles", []):
        combinaison = {}
        for code, valeur in {**r["si"], **r["interdit"]}.items():
            valeurs = attributs[code]["valeurs"]
            if valeur not in valeurs:
                raise ValueError(f"Règle « {r['nom']} » : valeur « {valeur} » inconnue pour {code}")
            combinaison[int(code[1:])] = valeurs.index(valeur)
        regles.append((r["nom"], combinaison))
    return regles


def violations(P, regles):
    """Pour chaque règle, masque des lignes de P (individus ou personas) qui la violent."""
    P = np.asarray(P)
    res = []
    for nom, comb in regles:
        m = np.ones(len(P), dtype=bool)
        for a, v in comb.items():
            m &= P[:, a] == v
        res.append((nom, m))
    return res


def filtrer(X, u_max, regles, afficher=True):
    """Retire les personas qui violent une règle. Renvoie (X, u_max) filtrés."""
    garde = np.ones(len(X), dtype=bool)
    for nom, m in violations(X, regles):
        if afficher:
            print(f"  Règle « {nom} » : {m.sum()} personas retirées")
        garde &= ~m
    if afficher:
        print(f"  Personas actives : {len(X)} -> {garde.sum()}")
    return X[garde], u_max[garde]


def compter_violations(P, regles):
    return {nom: int(m.sum()) for nom, m in violations(P, regles)}
