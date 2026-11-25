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
        # crédibilité (juge et chiffres)
        "accords_valides": proportion(acc["valide"]) if len(acc) else None,
        "chiffres_inventes": proportion(ok["chiffres_inventes"].dropna() > 0) if "chiffres_inventes" in ok else None,
        "scenes_jugees": int(ok["jugee"].sum()) if "jugee" in ok else 0,
        "note_fidelite": moyenne(ok["juge_fidelite"]) if "juge_fidelite" in ok else None,
        "note_coherence": moyenne(ok["juge_coherence"]) if "juge_coherence" in ok else None,
        "note_naturel": moyenne(ok["juge_naturel"]) if "juge_naturel" in ok else None,
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



# ---------------------------------------------------------------------------
# Concessions et personnalité
# ---------------------------------------------------------------------------
TRAITS = {"ouverture": "Ouverture", "conscienciosite": "Rigueur", "extraversion": "Extraversion",
          "agreabilite": "Agréabilité", "nevrosisme": "Anxiété"}
RESULTATS = {"accord": "Accord (scène)", "marge_preservee": "Marge préservée",
             "concession_part": "Concession"}


def participations(df, population):
    """Une ligne par agent et par négociation jouée (sans erreur) : ses traits, sa position, et
    ce qu'il en a tiré.
      accord           1 si la scène aboutit à un accord, 0 sinon ;
      marge_preservee  1 − hausse retenue / plafond secret (part de sa marge qu'il n'a pas dû céder) ;
      concession_part  chemin fait vers les autres entre sa première proposition et l'accord,
                       en part du budget annuel (voir negociation.concessions)."""
    ok = df[(df["erreur"].isna()) & (df["mode"] == "negociation") & df["accord"].notna()]
    pop = population.set_index("id")
    lignes = []
    for _, r in ok.iterrows():
        conc = {c["nom"]: c for c in (r["concessions"] or [])} if isinstance(r["concessions"], list) else {}
        for k, i in enumerate(r["ids"]):
            if int(i) not in pop.index:
                continue
            p = pop.loc[int(i)]
            hausses, plafonds = r.get("hausses"), r.get("plafonds")
            mp = None
            if isinstance(hausses, list) and isinstance(plafonds, list) and plafonds[k]:
                mp = round(1 - hausses[k] / plafonds[k], 3)
            c = conc.get(r["noms"][k], {})
            lignes.append({"scene_id": r["scene_id"], "id": int(i), "nom": r["noms"][k],
                           "position": r["positions"][k], "taille": int(r["taille"]),
                           **{t: float(p[t]) for t in TRAITS},
                           "accord": 1.0 if r["accord"] is True else 0.0,
                           "marge_preservee": mp, "concession_part": c.get("concession_part")})
    return pd.DataFrame(lignes)


def correlation(x, y):
    """Corrélation de Pearson avec IC à 95 % (transformation de Fisher) et p-valeur approchée."""
    d = pd.DataFrame({"x": x, "y": y}).dropna()
    n = len(d)
    if n < 5 or d["x"].std() == 0 or d["y"].std() == 0:
        return {"r": None, "n": n}
    r = float(d["x"].corr(d["y"]))
    r = max(-0.9999, min(0.9999, r))
    z, se = math.atanh(r), 1 / math.sqrt(n - 3)
    t = r * math.sqrt((n - 2) / (1 - r * r))
    p = math.erfc(abs(t) / math.sqrt(2))                   # approximation normale, correcte dès n ≈ 30
    return {"r": r, "n": n, "bas": math.tanh(z - Z95 * se), "haut": math.tanh(z + Z95 * se), "p": p}


def analyse(df, population):
    """Corrélations entre chaque trait de personnalité et chaque résultat, plus les points
    pour les nuages de points."""
    part = participations(df, population)
    if part.empty:
        return {"lignes": [], "correlations": [], "concessions": [], "n_scenes": 0}
    corr = []
    for t, nom_t in TRAITS.items():
        for res, nom_r in RESULTATS.items():
            corr.append({"trait": t, "trait_nom": nom_t, "resultat": res, "resultat_nom": nom_r,
                         **correlation(part[t], part[res])})
    return {"lignes": part.to_dict("records"), "correlations": corr,
            "concessions": concessions_par_position(df), "n_scenes": int(part["scene_id"].nunique())}


def concessions_par_position(df):
    """Concession moyenne selon la position de l'agent (et la taille du groupe)."""
    lignes = []
    ok = df[(df["erreur"].isna()) & (df["mode"] == "negociation")]
    for _, r in ok.iterrows():
        if isinstance(r.get("concessions"), list):
            for c in r["concessions"]:
                if c.get("concession_part") is not None:
                    lignes.append({"position": c["position"], "taille": int(r["taille"]),
                                   "concession_part": c["concession_part"], "accord": r["accord"] is True})
    if not lignes:
        return []
    t = pd.DataFrame(lignes)
    out = []
    for (pos, taille), g in t.groupby(["position", "taille"]):
        out.append({"position": pos, "taille": int(taille), **(moyenne(g["concession_part"]) or {})})
    return out