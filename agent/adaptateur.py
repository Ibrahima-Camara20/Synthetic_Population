"""
Labo des agents - Adaptateur
============================

Le SEUL fichier du labo qui touche au code du projet (scene.py, personas.py,
llm.py). Si une fonction du projet change de nom ou de signature, c'est ici
qu'on corrige ; labo.py, journal.py et stats.py ne changent pas.

Ce que le labo attend de chaque scène (dictionnaire renvoyé par lancer_scene) :
    ids, noms, positions        les agents et leur position
    dialogue                    [(locuteur, texte), ...]
    zone                        options acceptables pour tous (None si inconnu)
    zone_vide                   True / False / None
    accord                      True / False / None
    proposition_finale          l'option acceptée (ou None)
    coherent                    accord compatible avec les marges : True / False / None
    mediateur                   True si le syndic est intervenu
    tour_accord                 numéro de la réplique où l'accord est conclu
    controles                   dict (verifier() de scene.py)
    duree_s, erreur

Les fonctions de négociation (zone d'accord, vérification des marges, médiateur)
sont cherchées par leur nom dans scene.py puis dans negociation.py. Si elles
n'existent pas (ancienne version), les champs correspondants valent None et le
labo l'indique ; l'accord est alors détecté par les balises [ACCORD].
"""

import contextlib
import importlib
import inspect
import io
import os
import re
import sys
import time

import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
if ICI not in sys.path:
    sys.path.insert(0, ICI)

import personas                        # noqa: E402
import scene                           # noqa: E402
from llm import ClientLLM, ErreurLLM   # noqa: E402

try:
    negociation = importlib.import_module("negociation")
except ImportError:
    negociation = None

# ---------------------------------------------------------------------------
# Noms possibles des fonctions de négociation (à ajuster à la branche main)
# ---------------------------------------------------------------------------
NOMS_ZONE = ["zone_accord", "zone_d_accord", "calculer_zone", "options_acceptables"]
NOMS_VERIF = ["verifier_accord", "accord_coherent", "verifier_marges", "respecte_marges"]
NOMS_MARGE = ["marge", "marge_secrete", "calculer_marge"]

BALISE_ACCORD = re.compile(r"\[\s*ACCORD\s*\]", re.I)


def _trouver(noms):
    for module in (scene, negociation):
        if module is None:
            continue
        for n in noms:
            f = getattr(module, n, None)
            if callable(f):
                return f
    return None


FONCTION_ZONE = _trouver(NOMS_ZONE)
FONCTION_VERIF = _trouver(NOMS_VERIF)
FONCTION_MARGE = _trouver(NOMS_MARGE)


def capacites():
    """Ce que la version du projet permet, affiché dans le labo."""
    params = inspect.signature(scene.jouer_scene).parameters
    return {
        "zone_accord": FONCTION_ZONE is not None,
        "verification_marges": FONCTION_VERIF is not None,
        "marge_secrete": FONCTION_MARGE is not None,
        "mediateur": "mediateur" in params,
        "trois_agents": "agents" in params or "c" in params,
    }


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------
def charger_population():
    chemin = os.path.join(ICI, "population_agents.csv")
    if os.path.exists(personas.POPULATION_FINALE) and not personas.est_a_jour(chemin):
        personas.generer_fichiers(afficher=False)
    df = pd.read_csv(chemin)
    df["particularites"] = df["particularites"].fillna("")
    df["traits"] = df["traits"].fillna("")
    return df


def agent(df, i):
    return df[df["id"] == int(i)].iloc[0]


def enjeux(p):
    return scene.enjeux(p)


def eligibles(df):
    return scene.eligibles(df)


def marge(p):
    """Marge secrète de l'agent (dict) si le projet sait la calculer."""
    if FONCTION_MARGE is None:
        return None
    try:
        m = FONCTION_MARGE(p)
        return m if isinstance(m, dict) else {"marge": m}
    except Exception as e:                    # noqa: BLE001
        return {"erreur": str(e)}


def zone(agents):
    """Options acceptables pour tous les agents, ou None si inconnu."""
    if FONCTION_ZONE is None:
        return None
    try:
        z = FONCTION_ZONE(*agents)
    except TypeError:
        z = FONCTION_ZONE(list(agents))
    return list(z) if z is not None else []


def choisir_paire(df, graine, ids=None):
    a, b = scene.choisir_paire(df, np.random.default_rng(graine), ids)
    return [a, b]


def fiche(p):
    return personas.texte_fiche(p)


# ---------------------------------------------------------------------------
# Lancer une scène
# ---------------------------------------------------------------------------
class _Flux(io.TextIOBase):
    """Capte les « Nom : réplique » que jouer_scene imprime, pour l'affichage en direct."""

    def __init__(self, rappel):
        self.rappel, self.tampon = rappel, ""

    def write(self, s):
        self.tampon += s
        while "\n" in self.tampon:
            ligne, self.tampon = self.tampon.split("\n", 1)
            if ligne.strip() and self.rappel:
                self.rappel(ligne.strip())
        return len(s)


def _normaliser(res):
    """jouer_scene peut renvoyer un tuple (ancienne version) ou un dict."""
    if isinstance(res, dict):
        return res
    if isinstance(res, tuple):
        return {"dialogue": res[0], "enjeux": list(res[1:])}
    return {"dialogue": res}


def _accord_balises(dialogue, noms):
    """Chaque agent a-t-il écrit [ACCORD] ? Renvoie (accord, index de la réplique)."""
    vus = set()
    for k, (loc, txt) in enumerate(dialogue):
        if BALISE_ACCORD.search(txt or ""):
            vus.add(loc)
            if set(noms) <= vus:
                return True, k + 1
    return False, None


def _texte(x):
    return x if isinstance(x, (str, int, float, bool, type(None))) else str(x)


def lancer_scene(agents, backend="test", modele=None, base_url=None, tours=12,
                 temperature=0.9, max_tokens=400, sans_reflexion=True, mediateur=True,
                 rappel=None):
    """Joue une scène et renvoie le dictionnaire décrit en tête de fichier."""
    t0 = time.perf_counter()
    noms = [f"{p['prenom']} {p['nom']}" for p in agents]
    ej = [enjeux(p) for p in agents]
    res = {
        "ids": [int(p["id"]) for p in agents], "noms": noms,
        "positions": [e["position"] for e in ej],
        "efforts_pct": [e["effort_pct"] for e in ej],
        "backend": backend, "modele": modele or "", "temperature": temperature,
        "tours_max": tours, "mediateur_actif": mediateur,
        "dialogue": [], "zone": None, "zone_vide": None, "accord": None,
        "proposition_finale": None, "coherent": None, "mediateur": False,
        "tour_accord": None, "controles": {}, "duree_s": 0.0, "erreur": None,
    }
    try:
        z = zone(agents)
        if z is not None:
            res["zone"] = [_texte(o) for o in z]
            res["zone_vide"] = len(z) == 0

        client = ClientLLM(backend, modele, base_url, temperature, max_tokens, sans_reflexion)
        kwargs = {"tours": tours}
        params = inspect.signature(scene.jouer_scene).parameters
        if "mediateur" in params:
            kwargs["mediateur"] = mediateur
        if "verbeux" in params:
            kwargs["verbeux"] = True
        if len(agents) == 3 and "agents" in params:
            args = ()
            kwargs.update(agents=list(agents), client=client)
        else:
            args = (*agents, client)

        with contextlib.redirect_stdout(_Flux(rappel)):
            brut = _normaliser(scene.jouer_scene(*args, **kwargs))

        dialogue = [tuple(x) if not isinstance(x, dict) else (x.get("locuteur"), x.get("texte"))
                    for x in brut.get("dialogue", [])]
        res["dialogue"] = dialogue
        res["controles"] = scene.verifier(dialogue, *agents[:2]) if dialogue else {}

        # Accord : ce que renvoie la scène, sinon les balises [ACCORD]
        if "accord" in brut:
            res["accord"] = bool(brut["accord"])
            res["tour_accord"] = brut.get("tour_accord")
        else:
            res["accord"], res["tour_accord"] = _accord_balises(dialogue, noms)
        res["proposition_finale"] = _texte(brut.get("proposition") or brut.get("proposition_finale"))
        res["mediateur"] = bool(brut.get("mediateur") or brut.get("mediateur_intervenu")
                                or any(str(l).lower().startswith("syndic") for l, _ in dialogue))

        # Cohérence avec les marges
        if "coherent" in brut:
            res["coherent"] = brut["coherent"]
        elif res["accord"] and FONCTION_VERIF is not None and brut.get("proposition") is not None:
            try:
                v = FONCTION_VERIF(brut["proposition"], *agents)
            except TypeError:
                v = FONCTION_VERIF(brut["proposition"], list(agents))
            res["coherent"] = bool(v if not isinstance(v, dict) else v.get("coherent", all(v.values())))
    except ErreurLLM as e:
        res["erreur"] = f"Modèle : {e}"
    except Exception as e:                    # noqa: BLE001
        res["erreur"] = f"{type(e).__name__} : {e}"
    res["duree_s"] = round(time.perf_counter() - t0, 1)
    return res
