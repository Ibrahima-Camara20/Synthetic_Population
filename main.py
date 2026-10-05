"""
Population synthétique - Programme principal
============================================

Chaîne rapide (par défaut) :
  Étapes 1-2 : chargement, vérificateur, bornes        (etapes_1_2.py)
  Étapes 3-4 : glouton avec retour arrière -> exact    (glouton.py)
  Étape 6    : destruction-reconstruction des doublons (deduplication.py)

Mode comparaison (--comparaison) : affiche en plus, pour plusieurs graines,
le glouton simple et la dé-duplication par échanges (étape 5), pour montrer
l'apport de chaque étape.

Usage :
    python main.py                      # 60 s de dé-duplication
    python main.py --temps 120          # budget de temps de l'étape 6
    python main.py --comparaison        # tableau comparatif, puis étape 6
"""

import argparse
import contextlib
import io
import time
import numpy as np

from etapes_1_2 import charger_contraintes, calculer_bornes, verifier_population, K
from glouton import preparer, glouton, population_exacte
from deduplication import dedupliquer, reconstruire

FICHIER = "constraint_cells.csv"
OPTIMUM = 331      # maximum de personas distinctes, prouvé par solveur_reference.py


def entropie(P):
    """Entropie de Shannon (en bits) de la répartition des profils."""
    _, n = np.unique(P, axis=0, return_counts=True)
    p = n / n.sum()
    return float(-(p * np.log2(p)).sum())


def tableau_comparatif(tables, X, u_max, G, cibles, nb_graines):
    scopes = [t["scope"] for t in tables]
    print(f"{'graine':>6} | {'glouton simple':^14} | {'avec retour arrière':^22} | "
          f"{'+ échanges (étape 5)':^22}")
    print(f"{'':>6} | {'placés':>6} {'exact':>7} | {'distinctes':>10} {'temps':>10} | "
          f"{'distinctes':>10} {'temps':>10}")
    print("-" * 76)
    for g in range(nb_graines):
        c3, _ = glouton(G, cibles, u_max, np.random.default_rng(g), retour=False)
        r3 = verifier_population(X[c3], tables, afficher=False)
        c4, _, _, t4 = population_exacte(G, cibles, u_max, g)
        P4 = X[c4].astype(np.int64)
        t0 = time.perf_counter()
        P5, _ = dedupliquer(P4, scopes, np.random.default_rng(g))
        t5 = time.perf_counter() - t0
        r5 = verifier_population(P5, tables, afficher=False)
        assert r5["valide"]
        print(f"{g:>6} | {r3['taille']:>6} {str(r3['valide']):>7} | "
              f"{len(np.unique(P4, axis=0)):>10} {t4:>9.1f}s | "
              f"{r5['personas_distinctes']:>10} {t5:>9.1f}s", flush=True)
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--temps", type=float, default=60.0,
                        help="budget de temps (s) de l'étape 6")
    parser.add_argument("--graine", type=int, default=0)
    parser.add_argument("--comparaison", action="store_true",
                        help="affiche aussi le tableau comparatif des étapes")
    parser.add_argument("--graines", type=int, default=5,
                        help="nombre de graines du tableau comparatif")
    args = parser.parse_args()

    t_total = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        tables = charger_contraintes(FICHIER)
        X, u_max, _ = calculer_bornes(tables)
    G, cibles = preparer(tables, X)
    print(f"Étapes 1-2 : {len(tables)} tables, {len(cibles)} cellules, "
          f"{len(X)} personas actives ({time.perf_counter() - t_total:.1f} s)\n")

    if args.comparaison:
        tableau_comparatif(tables, X, u_max, G, cibles, args.graines)

    # Étapes 3-4 : population exacte
    choix, _, retours, t4 = population_exacte(G, cibles, u_max, args.graine)
    P = X[choix].astype(np.int64)
    print(f"Étapes 3-4 : population exacte en {t4:.1f} s ({retours} retours arrière), "
          f"{len(np.unique(P, axis=0))} personas distinctes")

    # Étape 6 : dé-duplication
    print(f"Étape 6    : destruction-reconstruction ({args.temps:.0f} s)")
    P, essais, amelio = reconstruire(P, X, G, cibles, u_max,
                                     np.random.default_rng(args.graine), duree=args.temps)
    print(f"             {essais} essais, {amelio} améliorations\n")

    print("=== Population finale ===")
    r = verifier_population(P, tables)
    assert r["valide"], "Population non exacte : bug"
    print(f"  Entropie              : {entropie(P):.2f} bits (max {np.log2(500):.2f})")
    print(f"  Part de l'optimum     : {r['personas_distinctes']} / {OPTIMUM} "
          f"= {100 * r['personas_distinctes'] / OPTIMUM:.0f} %")
    print(f"  Temps total           : {time.perf_counter() - t_total:.1f} s")
    np.savetxt("population_finale.csv", P, fmt="%d", delimiter=",",
               header=",".join(f"A{i}" for i in range(K)), comments="")
    print("Sauvegardé : population_finale.csv")


if __name__ == "__main__":
    main()