"""
Population synthétique - Étapes 1 et 2
=======================================

Étape 1 : charger les contraintes et vérifier une population.
Étape 2 : calculer les bornes u_x (max) et l_x (min) de chaque persona.

Usage :
    python etapes_1_2.py [constraint_cells.csv] [constraint_scopes.csv]
"""

import sys
import itertools
import numpy as np
import pandas as pd

K = 12          # nombre d'attributs A0..A11
D = 3           # nombre de valeurs par attribut v0, v1, v2
N = 500         # taille de la population


# =============================================================================
# ÉTAPE 1a : chargement des contraintes
# =============================================================================

def charger_contraintes(fichier_cells, fichier_scopes=None):
    """
    Lit constraint_cells.csv et renvoie une liste de tables.

    Chaque table est un dictionnaire :
        id     : numéro de la table (1..45)
        scope  : liste des attributs concernés, ex. [2, 3, 7, 9]
        cible  : tableau numpy de forme (3,)*arité ; cible[1,0,2] = nombre
                 d'individus devant avoir (1er attr = v1, 2e = v0, 3e = v2)
    """
    cells = pd.read_csv(fichier_cells)
    tables = []

    for tid, g in cells.groupby("table_id", sort=True):
        scope = [int(a[1:]) for a in g["scope"].iloc[0].split("|")]
        cible = np.full((D,) * len(scope), -1, dtype=np.int64)

        for texte, t in zip(g["cell"], g["target"]):
            # "A0=v1;A1=v0;A6=v2" -> (1, 0, 2)
            valeurs = {int(p.split("=")[0][1:]): int(p.split("=v")[1])
                       for p in texte.split(";")}
            cible[tuple(valeurs[a] for a in scope)] = t

        if (cible < 0).any():
            raise ValueError(f"Table {tid} : cellules manquantes")
        tables.append({"id": int(tid), "scope": scope, "cible": cible})

    # Contrôle de cohérence avec constraint_scopes.csv (si fourni)
    if fichier_scopes is not None:
        scopes = pd.read_csv(fichier_scopes).set_index("table_id")
        for t in tables:
            ligne = scopes.loc[t["id"]]
            scope_attendu = [int(a[1:]) for a in ligne["scope"].split("|")]
            assert t["scope"] == scope_attendu, f"Table {t['id']} : scope différent"
            assert t["cible"].size == ligne["num_cells"], f"Table {t['id']} : nb cellules"
            assert t["cible"].sum() == ligne["target_sum"], f"Table {t['id']} : somme"
        print(f"Cohérence cells/scopes : OK ({len(tables)} tables)")

    return tables


def index_cellule(pop, table):
    """
    Pour chaque ligne de pop (individu ou persona), renvoie le numéro de la
    cellule de la table dans laquelle elle tombe (entier entre 0 et 3^k - 1).
    """
    return np.ravel_multi_index(pop[:, table["scope"]].T, table["cible"].shape)


# =============================================================================
# ÉTAPE 1b : vérificateur
# =============================================================================

def verifier_population(pop, tables, afficher=True):
    """
    pop : tableau (n, 12) de valeurs 0/1/2, une ligne par individu.

    Renvoie un dictionnaire :
        ecart_total       : somme des |obtenu - cible| sur les 729 cellules
        cellules_violees  : nombre de cellules où obtenu != cible
        pire_table        : table avec le plus gros écart
        personas_distinctes, doublons, repetition_max
        valide            : True si toutes les cellules sont exactes
    """
    pop = np.asarray(pop)
    assert pop.ndim == 2 and pop.shape[1] == K, "pop doit être de forme (n, 12)"
    assert pop.min() >= 0 and pop.max() < D, "valeurs hors de {0,1,2}"

    ecart_total, violees = 0, 0
    pire = (0, None)
    ecarts_par_table = {}

    for t in tables:
        obtenu = np.bincount(index_cellule(pop, t), minlength=t["cible"].size)
        ecart = obtenu - t["cible"].ravel()
        ecarts_par_table[t["id"]] = ecart
        e = int(np.abs(ecart).sum())
        ecart_total += e
        violees += int((ecart != 0).sum())
        if e > pire[0]:
            pire = (e, t["id"])

    # Doublons : individus dont la persona est déjà apparue avant
    _, repetitions = np.unique(pop, axis=0, return_counts=True)
    distinctes = len(repetitions)

    res = {
        "taille": len(pop),
        "ecart_total": ecart_total,
        "cellules_violees": violees,
        "pire_table": pire[1],
        "ecart_pire_table": pire[0],
        "personas_distinctes": distinctes,
        "doublons": len(pop) - distinctes,
        "repetition_max": int(repetitions.max()),
        "valide": ecart_total == 0 and len(pop) == N,
        "ecarts_par_table": ecarts_par_table,
    }

    if afficher:
        print(f"  Taille                : {res['taille']}")
        print(f"  Écart total           : {res['ecart_total']}")
        print(f"  Cellules violées      : {res['cellules_violees']} / 729")
        if pire[1] is not None:
            print(f"  Pire table            : {pire[1]} (écart {pire[0]})")
        print(f"  Personas distinctes   : {distinctes}")
        print(f"  Doublons              : {res['doublons']}")
        print(f"  Répétition max        : {res['repetition_max']}")
        print(f"  VALIDE                : {res['valide']}")
    return res


# =============================================================================
# ÉTAPE 2 : bornes u_x et l_x
# =============================================================================

def toutes_les_personas():
    """Les 3^12 = 531 441 personas, sous forme d'un tableau (531441, 12)."""
    return np.array(list(itertools.product(range(D), repeat=K)), dtype=np.int8)


def borne_superieure_initiale(X, tables):
    """
    Diapo 14 : u_x = min des cibles des cellules qui contiennent x.
    Renvoie aussi, pour chaque table, l'index de cellule de chaque persona
    (réutilisé ensuite pour la propagation).
    """
    u = np.full(len(X), np.iinfo(np.int64).max, dtype=np.int64)
    idx = []
    for t in tables:
        c = index_cellule(X, t)
        idx.append(c)
        u = np.minimum(u, t["cible"].ravel()[c])
    return u, idx


def propager_bornes(u, l, idx, tables, max_iter=100):
    """
    Diapo 16 et formule générale diapo 14, appliquées jusqu'au point fixe.

    Pour chaque cellule S de cible M_S :
        l_x <- max(l_x, M_S - somme_{y dans S, y != x} u_y)
        u_x <- min(u_x, M_S - somme_{y dans S, y != x} l_y)

    Renvoie u, l et le nombre de tours effectués.
    """
    u, l = u.copy(), l.copy()
    for tour in range(1, max_iter + 1):
        change = False
        for t, c in zip(tables, idx):
            M = t["cible"].ravel()
            nb = M.size
            somme_u = np.bincount(c, weights=u, minlength=nb).astype(np.int64)
            somme_l = np.bincount(c, weights=l, minlength=nb).astype(np.int64)

            # Si les personas d'une cellule ne peuvent pas atteindre la cible,
            # ou si leurs minima la dépassent : problème infaisable.
            if (somme_u < M).any() or (somme_l > M).any():
                raise RuntimeError(f"Infaisable détecté sur la table {t['id']}")

            nouveau_l = np.maximum(l, M[c] - (somme_u[c] - u))
            nouveau_u = np.minimum(u, M[c] - (somme_l[c] - l))

            if (nouveau_l != l).any() or (nouveau_u != u).any():
                change = True
            l, u = nouveau_l, nouveau_u

        if (l > u).any():
            raise RuntimeError("Infaisable : une persona a l_x > u_x")
        if not change:
            return u, l, tour
    return u, l, max_iter


def calculer_bornes(tables):
    """Enchaîne toute l'étape 2 et affiche les tableaux des diapos 15, 17, 18."""
    X = toutes_les_personas()
    u0, idx = borne_superieure_initiale(X, tables)

    actives = u0 > 0
    print("\n--- Borne supérieure (diapo 15) ---")
    print(f"  Total personas            : {len(X)}")
    print(f"  Personas éliminées (u=0)  : {(~actives).sum()}")
    print(f"  Personas actives (u>0)    : {actives.sum()}")
    print(f"  Taux d'élimination        : {100 * (~actives).mean():.1f} %")
    print(f"  Somme des u_x             : {u0.sum()}")
    print(f"  u_x maximum               : {u0.max()}")
    print(f"  u_x minimum (actives)     : {u0[actives].min()}")
    print(f"  u_x moyenne (actives)     : {u0[actives].mean():.2f}")

    # On ne garde que les actives pour la propagation (bien plus rapide)
    Xa = X[actives]
    idx_a = [c[actives] for c in idx]
    ua, la, tours = propager_bornes(u0[actives], np.zeros(actives.sum(), dtype=np.int64),
                                    idx_a, tables)

    print(f"\n--- Borne inférieure (diapo 17), point fixe en {tours} tour(s) ---")
    print(f"  Personas avec l_x > 0      : {(la > 0).sum()}")
    print(f"  Personas avec l_x = u_x    : {((la == ua) & (ua > 0)).sum()}")
    print(f"  Somme des l_x              : {la.sum()}")
    reduites = (ua < u0[actives]).sum()
    print(f"  u_x resserrés par la propagation : {reduites}")
    print(f"  Personas actives après propagation : {(ua > 0).sum()}")
    print(f"  Somme des u_x après propagation    : {ua.sum()}")

    garder = ua > 0
    return Xa[garder], ua[garder], la[garder]


# =============================================================================
# Tests du vérificateur
# =============================================================================

def tests_verificateur(tables, rng):
    print("\n--- Test 1 : population aléatoire (doit échouer) ---")
    pop = rng.integers(0, D, size=(N, K))
    verifier_population(pop, tables)

    print("\n--- Test 2 : cibles recalculées depuis une population connue (doit réussir) ---")
    # On fabrique des tables dont les cibles sont exactement les marginales
    # d'une population aléatoire : le vérificateur doit trouver un écart nul.
    tables_test = []
    for t in tables:
        obtenu = np.bincount(index_cellule(pop, t), minlength=t["cible"].size)
        tables_test.append({**t, "cible": obtenu.reshape(t["cible"].shape)})
    r = verifier_population(pop, tables_test, afficher=False)
    assert r["valide"], "Le vérificateur devrait valider cette population"
    print("  OK : écart total 0, population reconnue comme valide")


# =============================================================================
# Programme principal
# =============================================================================

if __name__ == "__main__":
    f_cells = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/constraint_cells.csv"
    f_scopes = sys.argv[2] if len(sys.argv) > 2 else "/mnt/user-data/uploads/constraint_scopes.csv"

    print("=== ÉTAPE 1 : chargement et vérificateur ===")
    tables = charger_contraintes(f_cells, f_scopes)
    print(f"{len(tables)} tables, {sum(t['cible'].size for t in tables)} cellules")
    tests_verificateur(tables, np.random.default_rng(0))

    print("\n=== ÉTAPE 2 : bornes des personas ===")
    Xa, ua, la = calculer_bornes(tables)

    # Sauvegarde des personas actives pour l'étape 3 (glouton)
    sortie = pd.DataFrame(Xa, columns=[f"A{i}" for i in range(K)])
    sortie["u_max"] = ua
    sortie["l_min"] = la
    sortie.to_csv("personas_actives.csv", index=False)
    print(f"\nSauvegardé : personas_actives.csv ({len(sortie)} personas)")