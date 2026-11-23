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
    config, config_id           scénario, objectifs et critère utilisés (et leur empreinte)
    duree_s, erreur

Les fonctions de négociation (zone d'accord, vérification des marges, médiateur)
sont cherchées par leur nom dans scene.py puis dans negociation.py. Si elles
n'existent pas (ancienne version), les champs correspondants valent None et le
labo l'indique ; l'accord est alors détecté par les balises [ACCORD].

Configuration (scénario, objectifs, critère d'éligibilité)
----------------------------------------------------------
Une « config » est un dictionnaire :
    {"scenario": {...}, "objectifs": {...}, "eligibilite": "..."}
Les valeurs par défaut sont lues dans scene.py (SCENARIO, OBJECTIFS,
CRITERE_ELIGIBILITE). normaliser_config() complète et valide une config
reçue de la page ; les autres fonctions attendent une config déjà normalisée.
"""

import contextlib
import copy
import hashlib
import importlib
import inspect
import io
import json
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
        "scenario_modifiable": "scenario" in params and "objectifs" in params
                               and hasattr(scene, "OBJECTIFS"),
    }


# ---------------------------------------------------------------------------
# Configuration : scénario, objectifs, critère d'éligibilité
# ---------------------------------------------------------------------------
ETIQUETTES_SCENARIO = {"titre": "le titre", "lieu": "le lieu", "budget_annuel": "le budget annuel",
                       "projet": "le projet", "urgent": "les travaux urgents"}
ETIQUETTES_OBJECTIFS = {"contre": "l'objectif « contre »", "pour": "l'objectif « pour »",
                        "partage": "l'objectif « partagé »", "sante": "la nuance santé"}


def config_defaut():
    """La configuration actuellement définie dans scene.py."""
    return copy.deepcopy({
        "scenario": getattr(scene, "SCENARIO", {}),
        "objectifs": getattr(scene, "OBJECTIFS", {}),
        "eligibilite": getattr(scene, "CRITERE_ELIGIBILITE",
                               'logement == "proprietaire" and zone == "ville"'),
    })


def normaliser_config(config=None):
    """Complète une config reçue avec les valeurs par défaut et la valide.
    Lève ValueError (message en français) si une valeur est inutilisable."""
    cfg = config_defaut()
    recu = config or {}

    for cle in cfg["scenario"]:
        v = (recu.get("scenario") or {}).get(cle)
        if v is None:
            continue
        if cle == "budget_annuel":
            try:
                v = float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
            except ValueError:
                raise ValueError("Le budget annuel doit être un nombre.") from None
            if v <= 0:
                raise ValueError("Le budget annuel doit être supérieur à zéro.")
            v = int(v) if v == int(v) else v
        else:
            v = str(v).strip()
            if not v:
                raise ValueError(f"Le scénario ne peut pas avoir {ETIQUETTES_SCENARIO.get(cle, cle)} vide.")
        cfg["scenario"][cle] = v

    for cle in cfg["objectifs"]:
        v = (recu.get("objectifs") or {}).get(cle)
        if v is None:
            continue
        v = str(v).strip()
        if not v and cle != "sante":      # la nuance santé peut être supprimée
            raise ValueError(f"{ETIQUETTES_OBJECTIFS.get(cle, cle).capitalize()} ne peut pas être vide.")
        cfg["objectifs"][cle] = v

    if recu.get("eligibilite") is not None:
        cfg["eligibilite"] = " ".join(str(recu["eligibilite"]).split())
    return cfg


def empreinte(cfg):
    """Court identifiant d'une configuration, pour comparer des essais."""
    brut = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(brut.encode("utf-8")).hexdigest()[:6]


def colonnes_info(df):
    """Colonnes utilisables dans le critère d'éligibilité, avec leurs valeurs possibles."""
    info = {}
    for c in df.columns:
        if c.startswith("z_"):
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            info[c] = None                       # nombre
        else:                                    # texte (type object ou str selon la version de pandas)
            valeurs = sorted(df[c].dropna().astype(str).unique())
            if len(valeurs) <= 12:
                info[c] = valeurs
    return info


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


def enjeux(p, cfg=None):
    cfg = cfg or normaliser_config()
    return scene.enjeux(p, cfg["scenario"], cfg["objectifs"])


def eligibles(df, cfg=None):
    cfg = cfg or normaliser_config()
    return scene.eligibles(df, cfg["eligibilite"])


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


def choisir_paire(df, graine, ids=None, cfg=None):
    """Paire « pour / contre » choisie parmi les meilleures (grand écart d'effort)."""
    cfg = cfg or normaliser_config()
    try:
        a, b = scene.choisir_paire(df, np.random.default_rng(graine), ids,
                                   cfg["scenario"], cfg["objectifs"], cfg["eligibilite"])
    except SystemExit as e:                   # scene.py arrête le programme : ici, simple erreur
        raise ValueError(str(e)) from None
    return [a, b]


def tirer_groupes(df, n, graine, taille=2, opposes=False, cfg=None):
    """Tire n groupes d'agents au hasard parmi les éligibles (une paire par scène).

    opposes=False : agents tirés au hasard, sans condition sur leur position.
    opposes=True  : un agent « pour » (qui commence) et un agent « contre », tirés
                    au hasard ; un éventuel troisième agent est tiré parmi les autres.
    Les groupes déjà tirés dans la série ne sont pas rejoués tant que c'est possible.
    Renvoie une liste de listes d'identifiants.
    """
    cfg = cfg or normaliser_config()
    el = scene.eligibles(df, cfg["eligibilite"])
    ids = [int(i) for i in el["id"]]
    if len(ids) < taille:
        raise ValueError(f"Il faut au moins {taille} agents éligibles "
                         f"(il y en a {len(ids)} avec ce critère).")
    rng = np.random.default_rng(graine)
    pour, contre = [], []
    if opposes:
        for _, p in el.iterrows():
            pos = scene.enjeux(p, cfg["scenario"], cfg["objectifs"])["position"]
            if pos == "pour":
                pour.append(int(p["id"]))
            elif pos == "contre":
                contre.append(int(p["id"]))
        if not pour or not contre:
            raise ValueError("Aucune paire « pour / contre » parmi les agents éligibles avec "
                             "ce scénario : choisissez le tirage « tous les éligibles ».")
    groupes, vus = [], set()
    for _ in range(n):
        g = None
        for _essai in range(200):
            if opposes:
                g = [int(rng.choice(pour)), int(rng.choice(contre))]
                if taille == 3:
                    g.append(int(rng.choice([i for i in ids if i not in g])))
            else:
                g = [int(i) for i in rng.choice(ids, size=taille, replace=False)]
            if frozenset(g) not in vus:
                break
        vus.add(frozenset(g))
        groupes.append(g)
    return groupes


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
                 config=None, rappel=None):
    """Joue une scène et renvoie le dictionnaire décrit en tête de fichier."""
    t0 = time.perf_counter()
    cfg = config or normaliser_config()
    noms = [f"{p['prenom']} {p['nom']}" for p in agents]
    ej = [enjeux(p, cfg) for p in agents]
    res = {
        "ids": [int(p["id"]) for p in agents], "noms": noms,
        "positions": [e["position"] for e in ej],
        "efforts_pct": [e["effort_pct"] for e in ej],
        "backend": backend, "modele": modele or "", "temperature": temperature,
        "tours_max": tours, "mediateur_actif": mediateur,
        "config": cfg, "config_id": empreinte(cfg),
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
        if "scenario" in params:
            kwargs["scenario"] = cfg["scenario"]
        if "objectifs" in params:
            kwargs["objectifs"] = cfg["objectifs"]
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
