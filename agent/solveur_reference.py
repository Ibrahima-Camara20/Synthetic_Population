"""
Population synthétique - Référence par solveur exact (OR-Tools CP-SAT)
======================================================================

Ce n'est PAS l'algorithme demandé (un glouton) : ce script sert uniquement de
point de comparaison. Il cherche la population exacte qui a le PLUS GRAND
nombre de personas distinctes, et prouve qu'on ne peut pas faire mieux.

Modèle :
    n_x  entier, 0 <= n_x <= u_x   nombre d'individus ayant la persona x
    y_x  booléen, y_x <= n_x       vaut 1 si la persona x est utilisée
    pour chaque cellule C : somme des n_x des personas de C = cible(C)
    maximiser la somme des y_x     (= nombre de personas distinctes)

Usage :
    pip install ortools
    python solveur_reference.py [secondes] [population_de_depart.csv]
La population de départ (par ex. population_finale.csv) sert d'indice au
solveur pour démarrer plus vite.
"""

import sys
import time
import contextlib
import io
import numpy as np
from ortools.sat.python import cp_model

from etapes_1_2 import charger_contraintes, calculer_bornes, verifier_population, K
from glouton import preparer
from deduplication import PUISSANCES
import regles as rg

FICHIER = "/mnt/user-data/uploads/constraint_cells.csv"


def main(secondes=600.0, depart=None):
    with contextlib.redirect_stdout(io.StringIO()):
        tables = charger_contraintes(FICHIER)
        X, u_max, _ = calculer_bornes(tables)
    regles = rg.charger_regles()          # mêmes règles de cohérence que main.py
    if regles:
        X, u_max = rg.filtrer(X, u_max, regles)
    G, cibles = preparer(tables, X)

    indice = None
    if depart is not None:
        P = np.loadtxt(depart, delimiter=",", skiprows=1, dtype=np.int64)
        code = {int(c): i for i, c in enumerate(X.astype(np.int64) @ PUISSANCES)}
        indice = np.bincount([code[int(c)] for c in P @ PUISSANCES if int(c) in code],
                             minlength=len(X))

    m = cp_model.CpModel()
    n = [m.NewIntVar(0, int(u_max[i]), f"n{i}") for i in range(len(X))]
    y = [m.NewBoolVar(f"y{i}") for i in range(len(X))]
    membres = [[] for _ in range(len(cibles))]
    for i in range(len(X)):
        for cell in G[i]:
            membres[cell].append(i)
        m.Add(n[i] >= y[i])
        if indice is not None:
            m.AddHint(n[i], int(indice[i]))
            m.AddHint(y[i], int(indice[i] > 0))
    for cell, t in enumerate(cibles):
        m.Add(sum(n[i] for i in membres[cell]) == int(t))
    m.Maximize(sum(y))

    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = secondes
    t0 = time.perf_counter()
    statut = s.Solve(m)
    print(f"Statut : {s.StatusName(statut)}  ({time.perf_counter() - t0:.0f} s)")
    if statut not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return
    print(f"Meilleure solution : {s.ObjectiveValue():.0f} personas distinctes")
    print(f"Borne supérieure prouvée : {s.BestObjectiveBound():.0f}")

    pop = np.repeat(np.arange(len(X)), [s.Value(v) for v in n])
    verifier_population(X[pop], tables)
    np.savetxt("population_solveur.csv", X[pop], fmt="%d", delimiter=",",
               header=",".join(f"A{i}" for i in range(K)), comments="")
    print("Sauvegardé : population_solveur.csv")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 600.0,
         sys.argv[2] if len(sys.argv) > 2 else None)
