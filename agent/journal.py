"""
Labo des agents - Journal des scènes
====================================

Chaque scène jouée depuis le labo est ajoutée à scenes/journal.jsonl (une
ligne JSON par scène). C'est la base de toutes les statistiques : on peut
le relire, le filtrer, ou l'ouvrir dans pandas :

    import pandas as pd
    df = pd.read_json("scenes/journal.jsonl", lines=True)

Chaque ligne garde tout ce qu'il faut pour REPRODUIRE la scène : agents,
réglages du modèle, mode, configuration (scénario, objectifs, éligibilité,
marges), consignes envoyées aux agents, et, pour une expérience, la variante
et l'unité (paire + répétition) jouée.
"""

import json
import os
import threading
import uuid
from datetime import datetime

import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
CHEMIN = os.path.join(ICI, "scenes", "journal.jsonl")
_VERROU = threading.Lock()


def _propre(x):
    if hasattr(x, "item"):
        return x.item()
    if isinstance(x, (list, tuple)):
        return [_propre(v) for v in x]
    if isinstance(x, dict):
        return {k: _propre(v) for k, v in x.items()}
    return x


def ajouter(resultat, serie=None, etiquette="", **extra):
    """extra : experience, variante, unite, reglages_variante, mode_agents…"""
    os.makedirs(os.path.dirname(CHEMIN), exist_ok=True)
    ligne = {"scene_id": uuid.uuid4().hex[:8],
             "date": datetime.now().isoformat(timespec="seconds"),
             "serie": serie, "etiquette": etiquette, **_propre(extra), **_propre(resultat)}
    with _VERROU, open(CHEMIN, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def lire():
    if not os.path.exists(CHEMIN):
        return []
    with _VERROU, open(CHEMIN, encoding="utf-8") as f:
        lignes = []
        for l in f:
            if l.strip():
                try:
                    lignes.append(json.loads(l))
                except json.JSONDecodeError:          # ligne coupée (arrêt brutal) : ignorée
                    pass
        return lignes


def tableau():
    """Une ligne par scène, colonnes à plat (pour les statistiques)."""
    scenes = lire()
    if not scenes:
        return pd.DataFrame()
    df = pd.DataFrame(scenes)
    # Colonnes absentes des anciennes scènes du journal
    for c in ("config", "config_id", "mode_agents", "mode", "experience", "variante", "unite",
              "reglages_variante", "position_zone", "coherent", "zone_vide", "tour_accord",
              "mal_formees", "accord", "mediateur", "taille", "chiffres", "juge", "concessions",
              "propositions", "hausses", "plafonds"):
        if c not in df.columns:
            df[c] = None
    df["mode"] = df["mode"].fillna("ancien")
    df["agents"] = df["noms"].apply(lambda n: " / ".join(n))
    df["repliques"] = df["dialogue"].apply(len)
    df["mal_formees"] = df.apply(
        lambda r: r["mal_formees"] if pd.notna(r["mal_formees"]) else
        sum((r["controles"] or {}).get(k, 0) for k in ("codes_attributs", "en_tant_que", "mentions_ia"))
        if isinstance(r["controles"], dict) else 0, axis=1).astype(int)
    df["longueur_mots"] = df["controles"].apply(
        lambda c: c.get("longueur_moyenne_mots") if isinstance(c, dict) else None)
    df["mediateur"] = df["mediateur"].fillna(False).astype(bool)
    df["modele_complet"] = (df["backend"] + " " + df["modele"].fillna("")).str.strip()
    df["scenario_titre"] = df["config"].apply(
        lambda c: (c.get("scenario") or {}).get("titre", "") if isinstance(c, dict) else "")
    df["taille"] = df.apply(lambda r: r["taille"] if pd.notna(r["taille"]) else len(r["ids"]), axis=1).astype(int)

    # Évaluations du juge : la plus récente de juges.jsonl, sinon celle faite pendant la scène
    import juge
    jugees = juge.lire()

    def evaluation(r):
        j = jugees.get(r["scene_id"]) or (r["juge"] if isinstance(r["juge"], dict) and "erreur" not in r["juge"] else None)
        return j
    evals = df.apply(evaluation, axis=1)

    def fid(j):
        v = [x for x in ((j or {}).get("fidelite") or {}).values() if x is not None]
        return sum(v) / len(v) if v else None
    df["juge_fidelite"] = evals.apply(fid)
    df["juge_coherence"] = evals.apply(lambda j: (j or {}).get("coherence"))
    df["juge_naturel"] = evals.apply(lambda j: (j or {}).get("naturel"))
    df["juge_commentaire"] = evals.apply(lambda j: (j or {}).get("commentaire"))
    df["jugee"] = evals.notna()
    df["chiffres_inventes"] = df["chiffres"].apply(lambda c: c.get("inventes") if isinstance(c, dict) else None)
    df["valide"] = [juge.valide(c if isinstance(c, dict) else None, j) if isinstance(c, dict) or j else None
                    for c, j in zip(df["chiffres"], evals)]
    return df


def vider():
    """Met le journal (et les évaluations du juge) de côté dans une copie datée."""
    import juge
    date = f"{datetime.now():%Y%m%d_%H%M%S}"
    with _VERROU:
        for chemin in (CHEMIN, juge.CHEMIN):
            if os.path.exists(chemin):
                os.replace(chemin, f"{chemin}.{date}.bak")