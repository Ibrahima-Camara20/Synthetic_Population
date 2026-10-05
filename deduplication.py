"""
Population synthétique - Étape 5 : dé-duplication par échanges sûrs
===================================================================

On part d'une population EXACTE et on réduit les doublons en échangeant des
groupes d'attributs entre deux individus, uniquement quand l'échange ne
modifie aucune des 729 cellules. La population reste donc exacte à chaque pas.

Quand un échange est-il sûr ?
  Deux individus i et j diffèrent sur un ensemble D d'attributs. On échange un
  sous-ensemble T de D. Pour une table de scope S, notons D_S = S ∩ D :
    - si T ne touche pas D_S : i et j sont identiques sur S ∩ T, la table ne
      voit aucun changement ;
    - si T contient tout D_S : i et j sont identiques sur S \\ T, ils échangent
      simplement leurs cellules, les comptes ne changent pas.
  Chaque D_S doit donc être pris en entier ou pas du tout. Les attributs liés
  par un même D_S forment un « bloc », et on peut échanger n'importe quel bloc.

Nécessite etapes_1_2.py dans le même dossier.
"""

import itertools
import numpy as np

from etapes_1_2 import N, K

PUISSANCES = 3 ** np.arange(K)[::-1]      # code entier unique d'une persona


def blocs_echangeables(vi, vj, scopes):
    """Blocs d'attributs échangeables sans risque entre les individus vi et vj."""
    D = [a for a in range(K) if vi[a] != vj[a]]
    if len(D) < 2:
        return []
    parent = {a: a for a in D}

    def racine(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    Dset = set(D)
    for S in scopes:
        DS = [a for a in S if a in Dset]
        for b in DS[1:]:
            parent[racine(b)] = racine(DS[0])

    blocs = {}
    for a in D:
        blocs.setdefault(racine(a), []).append(a)
    blocs = list(blocs.values())
    # Un seul bloc = échanger i et j en entier, ce qui ne change rien
    return blocs if len(blocs) >= 2 else []


def sous_ensembles(blocs, max_unions=15):
    """Tous les groupes de blocs utiles (sans le vide ni le tout), au plus max_unions."""
    b = len(blocs)
    res = []
    for taille in range(1, b):
        for combi in itertools.combinations(range(b), taille):
            res.append(sorted(a for i in combi for a in blocs[i]))
            if len(res) >= max_unions:
                return res
    return res


def dedupliquer(P, scopes, rng, max_iter=300000, patience=40000, p_neutre=0.3):
    """
    P : population exacte, tableau (500, 12).

    À chaque itération : on prend un individu en double i et un individu j au
    hasard, on cherche l'échange sûr qui augmente le plus le nombre de personas
    distinctes. On l'applique s'il améliore ; s'il est neutre, on l'applique
    avec la probabilité p_neutre, pour explorer.

    On s'arrête après `patience` itérations sans nouveau record.
    Renvoie (meilleure population trouvée, nombre d'itérations).
    """
    P = P.copy()
    code = P @ PUISSANCES
    compte = {}
    for c in code:
        compte[c] = compte.get(c, 0) + 1

    def variation(anciens, nouveaux):
        """Variation du nombre de personas distinctes."""
        modif = {}
        for c in anciens:
            modif[c] = modif.get(c, 0) - 1
        for c in nouveaux:
            modif[c] = modif.get(c, 0) + 1
        v = 0
        for c, m in modif.items():
            avant = compte.get(c, 0)
            v += (avant + m > 0) - (avant > 0)
        return v

    meilleur_nb, meilleure = len(compte), P.copy()
    sans_progres = 0

    for it in range(max_iter):
        if sans_progres > patience:
            break
        doubles = [i for i in range(N) if compte[code[i]] > 1]
        if not doubles:
            break
        i = doubles[rng.integers(len(doubles))]
        j = int(rng.integers(N))
        blocs = blocs_echangeables(P[i], P[j], scopes) if i != j else []
        if not blocs:
            sans_progres += 1
            continue

        best = None
        for T in sous_ensembles(blocs):
            ni, nj = P[i].copy(), P[j].copy()
            ni[T], nj[T] = P[j][T], P[i][T]
            ci, cj = int(ni @ PUISSANCES), int(nj @ PUISSANCES)
            v = variation([code[i], code[j]], [ci, cj])
            if best is None or v > best[0]:
                best = (v, ni, nj, ci, cj)

        v, ni, nj, ci, cj = best
        if v > 0 or (v == 0 and rng.random() < p_neutre):
            for c in (code[i], code[j]):
                compte[c] -= 1
                if compte[c] == 0:
                    del compte[c]
            for c in (ci, cj):
                compte[c] = compte.get(c, 0) + 1
            P[i], P[j], code[i], code[j] = ni, nj, ci, cj

        if len(compte) > meilleur_nb:
            meilleur_nb, meilleure = len(compte), P.copy()
            sans_progres = 0
        else:
            sans_progres += 1

    return meilleure, it


# =============================================================================
# Étape 6 : destruction-reconstruction d'un petit groupe
# =============================================================================
#
# Les échanges à deux individus atteignent une limite : tout remplacement de
# deux individus par deux autres qui conserve les marginales est forcément un
# échange de blocs (à cause des tables d'arité 1). Pour aller plus loin, on
# remplace un groupe de q individus d'un coup :
#   1. on retire q individus : moitié parmi les doublons, en visant surtout les
#      PETITS doublons (profils répétés 2, 3, 4 fois…), moitié au hasard ;
#   2. les cellules qu'ils occupaient laissent un « trou » dans les marginales ;
#   3. on remplit ce trou avec le glouton avec retour arrière, les autres
#      individus restant fixes ;
#   4. on garde la nouvelle population si elle n'a pas moins de personas
#      distinctes que l'ancienne, sinon on revient en arrière.
#
# Pourquoi viser les petits doublons ? La solution optimale (solveur exact)
# concentre les répétitions dans quelques gros profils apparemment
# inévitables et rend presque tout le reste unique. Retirer des copies des gros
# profils est donc presque toujours inutile ; ce sont les petits doublons
# qu'il faut transformer en profils uniques.
# La population reste exacte à chaque étape.

def reconstruire(P, X, G, cibles, u_max, rng, q=20, duree=60.0, puissance=2.0,
                 bonus=3.0, afficher=True):
    """
    P      : population exacte, tableau (500, 12)
    X      : personas actives (étape 2), G et cibles : voir glouton.preparer
    q      : taille du groupe détruit puis reconstruit
    duree  : budget de temps en secondes
    puissance : un doublon dont le profil a k copies est tiré avec un poids
                1 / k^puissance (0 = tirage uniforme)
    bonus  : bonus de score, pendant la reconstruction, pour une persona pas
             encore présente dans la population
    Renvoie (meilleure population, nombre d'essais, nombre d'améliorations).
    """
    from glouton import glouton            # import local : évite une dépendance circulaire
    import time

    code_vers_indice = {int(c): i for i, c in enumerate(X.astype(np.int64) @ PUISSANCES)}
    pop = np.array([code_vers_indice[int(c)] for c in P @ PUISSANCES])
    meilleur = len(np.unique(pop))
    t0, essais, ameliorations, prochain_affichage = time.perf_counter(), 0, 0, 0.0

    while time.perf_counter() - t0 < duree:
        essais += 1
        compte = np.bincount(pop, minlength=len(X))
        doubles = np.flatnonzero(compte[pop] > 1)
        if len(doubles) == 0:
            break

        # 1. Choix du groupe à détruire
        poids = 1.0 / compte[pop[doubles]] ** puissance
        retires = set(rng.choice(doubles, size=min(q // 2, len(doubles)), replace=False,
                                 p=poids / poids.sum()).tolist())
        while len(retires) < q:
            retires.add(int(rng.integers(N)))
        garde = np.array([pop[i] for i in range(N) if i not in retires])

        # 2-3. Reconstruction exacte du trou, les autres individus restant fixes
        nouvelle, _ = glouton(G, cibles, u_max, rng, depart=garde, B=2, max_retours=20,
                              bonus=bonus)
        if len(nouvelle) < N:
            continue                         # reconstruction impossible : on oublie

        # 4. Acceptation si pas de perte de diversité
        nb = len(np.unique(nouvelle))
        if nb >= meilleur:
            ameliorations += nb > meilleur
            pop, meilleur = nouvelle, nb

        ecoule = time.perf_counter() - t0
        if afficher and ecoule >= prochain_affichage:
            print(f"    {ecoule:5.0f} s : {meilleur} personas distinctes", flush=True)
            prochain_affichage += 10

    return X[pop].astype(np.int64), essais, ameliorations