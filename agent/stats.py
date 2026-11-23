"""
Labo des agents - Statistiques
==============================

Les mesures se calculent sur le journal des scènes (journal.tableau()).

Chaque proportion est donnée avec son effectif et un intervalle de confiance à
95 % (méthode de Wilson, correcte même pour de petits effectifs ou des taux
proches de 0 ou 100 %) : avec 10 scènes, « 60 % » veut dire « entre 31 et 83 % ».

Pour une expérience (mêmes paires d'agents jouées par chaque variante), les
variantes sont comparées à la variante de référence PAIRE PAR PAIRE avec le
test exact de McNemar : on ne compte que les paires où les deux variantes
diffèrent (accord avec l'une, pas avec l'autre).
"""

import math

import pandas as pd

Z95 = 1.959964


def proportion(serie):
    """Proportion de True (les NaN / None sont ignorés), avec IC de Wilson à 95 %."""
    s = pd.Series(serie).dropna()
    n = int(len(s))
    if n == 0:
        return None
    k = int(s.astype(bool).sum())
    p = k / n
    centre = (p + Z95 ** 2 / (2 * n)) / (1 + Z95 ** 2 / n)
    demi = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / (1 + Z95 ** 2 / n)
    return {"k": k, "n": n, "p": p, "bas": max(0.0, centre - demi), "haut": min(1.0, centre + demi)}


def moyenne(serie):
    s = pd.to_numeric(pd.Series(serie), errors="coerce").dropna()
    if not len(s):
        return None
    return {"n": int(len(s)), "moy": float(s.mean()), "et": float(s.std(ddof=1)) if len(s) > 1 else 0.0}


def _vrai(df, col):
    if col not in df:
        return pd.Series(False, index=df.index, dtype=bool)
    return df[col].apply(lambda v: v is True or v == 1).astype(bool)


def mesures(df):
    """Les mesures du labo pour un ensemble de scènes."""
    if df.empty:
        return {}
    ok = df[df["erreur"].isna()]
    nego = ok[ok["mode"] == "negociation"]
    avec_zone = nego[nego["zone_vide"] == False]          # noqa: E712
    zone_vide = nego[nego["zone_vide"] == True]           # noqa: E712
    acc = nego[_vrai(nego, "accord")]
    return {
        "scenes": int(len(ok)),
        "erreurs": int((df["erreur"].notna() & (df["erreur"] != "Interrompue")).sum()),
        "interrompues": int((df["erreur"] == "Interrompue").sum()),
        "negociations": int(len(nego)),
        # convergence
        "accord": proportion(nego["accord"]),
        "accord_zone": proportion(avec_zone["accord"]),
        "accord_zone_vide": proportion(zone_vide["accord"]),          # doit rester à 0
        # qualité de l'accord
        "coherent": proportion(acc["coherent"]),
        "sans_mediateur": proportion(~acc["mediateur"].astype(bool)) if len(acc) else None,
        "position_zone": moyenne(acc[_vrai(acc, "coherent")]["position_zone"]),
        "tour_accord": moyenne(acc["tour_accord"]),
        # qualité du jeu
        "scenes_mal_formees": proportion(ok["mal_formees"] > 0),
        "longueur_mots": moyenne(ok["longueur_mots"]),
        "duree_s": moyenne(ok["duree_s"]),
    }


def par_groupe(df, colonnes):
    """Les mêmes mesures, une ligne par valeur de `colonnes` (ex. ['modele_complet'])."""
    if df.empty or not colonnes:
        return []
    lignes = []
    for cle, g in df.groupby(colonnes, dropna=False):
        cle = cle if isinstance(cle, tuple) else (cle,)
        lignes.append({**{c: (None if pd.isna(v) else v) for c, v in zip(colonnes, cle)}, **mesures(g)})
    return lignes


# ---------------------------------------------------------------------------
# Expériences : comparaison appariée des variantes
# ---------------------------------------------------------------------------
def mcnemar_exact(b, c):
    """p-valeur bilatérale du test exact de McNemar (b, c = paires discordantes)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    queue = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * queue)


def comparer(df, reference, critere="accord"):
    """Compare chaque variante à la référence sur les mêmes unités (paire + répétition).
    Renvoie une ligne par variante : taux, différence, paires discordantes, p-valeur."""
    ok = df[df["erreur"].isna() & df[critere].notna()]
    if ok.empty or reference not in set(ok["variante"]):
        return []
    tab = ok.pivot_table(index="unite", columns="variante", values=critere,
                         aggfunc=lambda s: bool(s.iloc[0]))
    lignes = []
    for v in tab.columns:
        if v == reference:
            continue
        paires = tab[[reference, v]].dropna()
        ref, var = paires[reference].astype(bool), paires[v].astype(bool)
        b = int((var & ~ref).sum())          # mieux que la référence
        c = int((ref & ~var).sum())          # moins bien
        lignes.append({"variante": v, "unites": int(len(paires)),
                       "taux_reference": float(ref.mean()) if len(paires) else None,
                       "taux_variante": float(var.mean()) if len(paires) else None,
                       "difference": float(var.mean() - ref.mean()) if len(paires) else None,
                       "gagne": b, "perd": c, "p_valeur": mcnemar_exact(b, c)})
    return lignes


def resume_experience(df):
    """Mesures par variante + comparaison appariée à la première variante (la référence)."""
    if df.empty:
        return {}
    rang = df["variante_rang"] if "variante_rang" in df else pd.Series(0, index=df.index)
    ordre = list(dict.fromkeys(df.assign(_r=rang.fillna(0)).sort_values(["_r", "date"])["variante"]))
    reference = ordre[0]
    variantes = []
    for v in ordre:
        g = df[df["variante"] == v]
        variantes.append({"variante": v, "reglages": g.iloc[0].get("reglages_variante"), **mesures(g)})
    return {"reference": reference, "variantes": variantes,
            "comparaison_accord": comparer(df, reference, "accord"),
            "comparaison_coherent": comparer(df[_vrai(df, "accord")], reference, "coherent"),
            "unites": int(df["unite"].nunique())}