"""
Labo des agents - Journal des scènes
====================================

Chaque scène jouée depuis le labo est ajoutée à scenes/journal.jsonl (une
ligne JSON par scène). C'est la base de toutes les statistiques : on peut
le relire, le filtrer, ou l'ouvrir dans pandas.

Chaque ligne garde aussi la configuration utilisée (scénario, objectifs,
critère d'éligibilité) et le mode de tirage des agents, pour comparer des essais.
"""

import json
import os
import uuid
from datetime import datetime

import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
CHEMIN = os.path.join(ICI, "scenes", "journal.jsonl")


def _propre(x):
    if hasattr(x, "item"):
        return x.item()
    if isinstance(x, (list, tuple)):
        return [_propre(v) for v in x]
    if isinstance(x, dict):
        return {k: _propre(v) for k, v in x.items()}
    return x


def ajouter(resultat, serie=None, etiquette=""):
    os.makedirs(os.path.dirname(CHEMIN), exist_ok=True)
    ligne = {"scene_id": uuid.uuid4().hex[:8],
             "date": datetime.now().isoformat(timespec="seconds"),
             "serie": serie, "etiquette": etiquette, **_propre(resultat)}
    with open(CHEMIN, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def lire():
    if not os.path.exists(CHEMIN):
        return []
    with open(CHEMIN, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def tableau():
    """Une ligne par scène, colonnes à plat (pour les statistiques)."""
    scenes = lire()
    if not scenes:
        return pd.DataFrame()
    df = pd.DataFrame(scenes)
    # Colonnes absentes des anciennes scènes du journal
    for c in ("config", "config_id", "mode_agents"):
        if c not in df.columns:
            df[c] = None
    df["agents"] = df["noms"].apply(lambda n: " / ".join(n))
    df["nb_agents"] = df["ids"].apply(len)
    df["repliques"] = df["dialogue"].apply(len)
    df["mal_formees"] = df["controles"].apply(
        lambda c: sum(c.get(k, 0) for k in ("codes_attributs", "en_tant_que", "mentions_ia"))
        if isinstance(c, dict) else 0)
    df["modele_complet"] = (df["backend"] + " " + df["modele"].fillna("")).str.strip()
    df["scenario_titre"] = df["config"].apply(
        lambda c: (c.get("scenario") or {}).get("titre", "") if isinstance(c, dict) else "")
    return df


def vider():
    if os.path.exists(CHEMIN):
        os.replace(CHEMIN, CHEMIN + f".{datetime.now():%Y%m%d_%H%M%S}.bak")
