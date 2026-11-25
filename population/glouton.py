"""
Population synthétique - Étapes 3 et 4 : glouton par tension avec retour arrière
================================================================================

Principe :
  - On construit les 500 individus un par un, en choisissant à chaque pas une
    persona qui aide les cellules « tendues » (résidu grand par rapport aux
    places encore disponibles).
  - Après chaque choix, on vérifie qu'aucune cellule n'a besoin de plus
    d'individus qu'il ne reste de places possibles. Si c'est le cas, l'impasse
    est inévitable : on défait les derniers choix (retour arrière) et on
    recommence, en reculant de plus en plus loin si l'impasse se répète.

Nécessite etapes_1_2.py dans le même dossier.
"""

import time
import numpy as np

from etapes_1_2 import index_cellule, N


def preparer(tables, X):
    """
    Numérote les 729 cellules de 0 à 728.
    Renvoie :
        G      : tableau (nb_personas, 45), G[x, t] = numéro de la cellule de la
                 table t dans laquelle tombe la persona x
        cibles : tableau (729,) des cibles dans la même numérotation
    """
    decalage, colonnes, cibles = 0, [], []
    for t in tables:
        colonnes.append(index_cellule(X, t) + decalage)
        cibles.append(t["cible"].ravel())
        decalage += t["cible"].size
    return np.stack(colonnes, axis=1), np.concatenate(cibles).astype(np.int64)


def glouton(G, cibles, u_max, rng, k=5, retour=True, B=5, max_retours=300,
            plafond=None, lam=0.0, depart=None, bonus=0.0):
    """
    G, cibles   : voir preparer()
    u_max       : nombre maximal d'utilisations de chaque persona (étape 2)
    rng         : générateur aléatoire (np.random.default_rng(graine))
    k           : tirage au hasard parmi les k meilleurs scores
    retour      : False = glouton simple de l'étape 3 (s'arrête au blocage)
    B           : nombre de choix défaits au 1er retour (doublé à chaque échec)
    max_retours : nombre maximal de retours arrière avant d'abandonner
    plafond     : nombre maximal de répétitions d'une même persona (None = u_max)
    lam         : pénalité par répétition déjà faite dans le score
    bonus       : bonus dans le score pour une persona pas encore utilisée
    depart      : population partielle de départ (indices de personas), que
                  le glouton complète ; None = on part de zéro

    Renvoie (liste des personas choisies, nombre de retours effectués).
    La population est exacte si et seulement si la liste a 500 éléments.
    """
    nb_cell = len(cibles)
    r = cibles.copy()                                   # résidus des cellules
    reste = u_max.astype(np.int64).copy()               # utilisations permises
    if plafond is not None:
        reste = np.minimum(reste, plafond)
    choix = [] if depart is None else [int(x) for x in depart]
    utilise = np.bincount(np.array(choix, dtype=np.int64), minlength=len(G))
    if choix:
        r -= np.bincount(G[choix].ravel(), minlength=nb_cell)
        reste -= utilise
    n_fixe = len(choix)                 # la population de départ n'est jamais défaite
    retours, echecs, record = 0, 0, len(choix)

    # Accélération : les résidus ne dépassent jamais leur valeur de départ (la
    # population de départ n'est jamais défaite), donc une persona impossible
    # maintenant le restera. On ne filtre ensuite que cette liste de base.
    base = np.flatnonzero((reste > 0) & (r[G] > 0).all(axis=1))

    while len(choix) < N:
        # Personas encore possibles
        cand = base[(reste[base] > 0) & (r[G[base]] > 0).all(axis=1)]
        cap = (np.bincount(G[cand].ravel(), weights=np.repeat(reste[cand], G.shape[1]),
                           minlength=nb_cell) if len(cand) else np.zeros(nb_cell))

        # Impasse : plus de candidate, ou (avec retour arrière) une cellule
        # qu'on ne pourra plus remplir. Sans retour arrière, on continue
        # jusqu'au vrai blocage, comme le glouton simple de l'étape 3.
        impasse = len(cand) == 0 or (retour and (cap < r).any())
        if impasse:
            if not retour or retours >= max_retours or len(choix) == n_fixe:
                break
            retours += 1
            echecs += 1
            for _ in range(min(len(choix) - n_fixe, B * 2 ** (echecs - 1))):
                x = choix.pop()
                r[G[x]] += 1
                reste[x] += 1
                utilise[x] -= 1
            continue

        # Score : somme des tensions de ses 45 cellules, moins la pénalité
        tension = np.divide(r, cap, out=np.zeros(nb_cell), where=cap > 0)
        score = tension[G[cand]].sum(axis=1) - lam * utilise[cand] + bonus * (utilise[cand] == 0)
        kk = min(k, len(cand))
        x = cand[rng.choice(np.argpartition(-score, kk - 1)[:kk])]

        choix.append(x)
        r[G[x]] -= 1
        reste[x] -= 1
        utilise[x] += 1
        if len(choix) > record:           # nouveau record : on repart à B
            record, echecs = len(choix), 0

    return np.array(choix, dtype=np.int64), retours


def population_exacte(G, cibles, u_max, graine, max_relances=20, **options):
    """
    Lance le glouton avec retour arrière ; s'il abandonne, relance avec une
    autre graine. Renvoie (choix, nombre de relances, retours, durée).
    """
    t0 = time.perf_counter()
    for relance in range(max_relances):
        rng = np.random.default_rng(1000 * graine + relance)
        choix, retours = glouton(G, cibles, u_max, rng, **options)
        if len(choix) == N:
            return choix, relance, retours, time.perf_counter() - t0
    return None, max_relances, retours, time.perf_counter() - t0