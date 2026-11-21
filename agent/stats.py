"""
Labo des agents - Statistiques sur les scènes jouées
====================================================

Mesures (toutes calculées sur le journal) :
    scenes              nombre de scènes sans erreur
    taux_accord         accords / scènes
    accords_coherents   part des accords qui respectent les marges des agents
    sans_mediateur      part des accords conclus avant l'intervention du syndic
    zone_vide           scènes où aucun terrain d'entente n'existait
    accord_zone_vide    accords conclus malgré une zone vide (agents qui cèdent trop)
    tour_accord_moyen   réplique moyenne de l'accord
    mal_formees         répliques fautives (codes A0..A11, « en tant que », « IA »)
    duree_moyenne_s
"""

import numpy as np
import pandas as pd


def _part(serie):
    s = serie.dropna()
    return float(s.astype(bool).mean()) if len(s) else np.nan


def mesures(df):
    if df.empty:
        return {}
    ok = df[df["erreur"].isna()]
    acc = ok[ok["accord"] == True]                       # noqa: E712
    zv = ok[ok["zone_vide"] == True]                     # noqa: E712
    return {
        "scenes": len(ok),
        "erreurs": int(df["erreur"].notna().sum()),
        "taux_accord": _part(ok["accord"]),
        "accords_coherents": _part(acc["coherent"]) if len(acc) else np.nan,
        "sans_mediateur": float((~acc["mediateur"].astype(bool)).mean()) if len(acc) else np.nan,
        "zone_vide": int(len(zv)),
        "accord_zone_vide": _part(zv["accord"]) if len(zv) else np.nan,
        "tour_accord_moyen": float(acc["tour_accord"].dropna().mean()) if len(acc) else np.nan,
        "mal_formees": int(ok["mal_formees"].sum()),
        "duree_moyenne_s": float(ok["duree_s"].mean()) if len(ok) else np.nan,
    }


def par_groupe(df, colonnes):
    """Les mêmes mesures, une ligne par valeur de `colonnes` (ex. ['modele_complet'])."""
    if df.empty:
        return pd.DataFrame()
    lignes = []
    for cle, g in df.groupby(colonnes, dropna=False):
        cle = cle if isinstance(cle, tuple) else (cle,)
        lignes.append({**dict(zip(colonnes, cle)), **mesures(g)})
    return pd.DataFrame(lignes)
