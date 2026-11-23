"""
Labo des agents - Adaptateur
============================

Le SEUL fichier du labo qui touche au code du projet (scene.py, negociation.py,
personas.py, llm.py). Les appels sont explicites : si une fonction du projet
change de nom ou de signature, c'est ici qu'on corrige ; serveur.py, journal.py
et stats.py ne changent pas.

Deux modes de scène :
    negociation   les agents ont une marge secrète calculée depuis leur fiche, cherchent
                  une proposition commune et écrivent [ACCORD] ; le syndic peut intervenir ;
                  l'accord est extrait puis VÉRIFIÉ contre les marges (negociation.py).
    debat         l'ancienne scène de scene.py : chacun campe sur sa position.
                  Pas d'accord mesuré (champ accord = None).

Ce que le labo reçoit de chaque scène (dictionnaire renvoyé par lancer_scene) :
    ids, noms, positions, efforts_pct      les agents
    mode                                   negociation / debat
    dialogue                               [(locuteur, texte, accord_signale), ...]
    zone, zone_taille, zone_vide           options acceptables pour les deux
    accord                                 accord conclu et extrait (None en débat)
    proposition_finale, option             l'option retenue (texte, et postes + étalement)
    methode_extraction                     secretaire / mots_cles / script
    coherent, coherent_par_agent           l'option respecte-t-elle les marges ?
    position_zone                          0 = option la plus modeste de la zone, 1 = la plus ambitieuse
    hausses, plafonds                      hausse mensuelle de l'option et plafond de chaque agent
    mediateur, tour_syndic, tour_accord
    consignes                              prompts système de chaque agent (traçabilité)
    controles, mal_formees, duree_s, erreur

Configuration (onglet Scénario)
-------------------------------
    {"scenario": {...}, "objectifs": {...}, "eligibilite": "...",
     "marges": {"contre": 5, "partage": 6, "pour": 10}}      # plafonds en % du revenu
"""

import copy
import hashlib
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

import negociation as nego             # noqa: E402
import personas                        # noqa: E402
import scene                           # noqa: E402
from llm import ClientLLM, ErreurLLM   # noqa: E402

MODES = ("negociation", "debat")


class Interrompu(Exception):
    """Arrêt demandé depuis le labo."""


# ---------------------------------------------------------------------------
# Configuration : scénario, objectifs, critère d'éligibilité, marges
# ---------------------------------------------------------------------------
ETIQUETTES_SCENARIO = {"titre": "le titre", "lieu": "le lieu", "budget_annuel": "le budget annuel",
                       "projet": "le projet", "urgent": "les travaux urgents"}
ETIQUETTES_OBJECTIFS = {"contre": "l'objectif « contre »", "pour": "l'objectif « pour »",
                        "partage": "l'objectif « partagé »", "sante": "la nuance santé"}


def config_defaut():
    """La configuration actuellement définie dans scene.py et negociation.py."""
    return copy.deepcopy({
        "scenario": scene.SCENARIO,
        "objectifs": scene.OBJECTIFS,
        "eligibilite": scene.CRITERE_ELIGIBILITE,
        "marges": nego.MARGES,
    })


def _nombre(v, quoi):
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace("\xa0", "").replace(",", "."))
    except ValueError:
        raise ValueError(f"{quoi} doit être un nombre.") from None


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
            v = _nombre(v, "Le budget annuel")
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

    for cle in cfg["marges"]:
        v = (recu.get("marges") or {}).get(cle)
        if v is None or v == "":
            continue
        v = _nombre(v, f"La marge « {cle} »")
        if not 0 < v <= 100:
            raise ValueError(f"La marge « {cle} » doit être comprise entre 0 et 100 % du revenu.")
        cfg["marges"][cle] = v
    return cfg


def empreinte(cfg):
    """Court identifiant d'une configuration, pour comparer des essais."""
    brut = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(brut.encode("utf-8")).hexdigest()[:6]


def regles(cfg):
    return nego.regles(cfg["scenario"], cfg["marges"])


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


def marge(p, cfg=None):
    """Marge secrète de l'agent, lisible (onglet Population)."""
    cfg = cfg or normaliser_config()
    R = regles(cfg)
    e = enjeux(p, cfg)
    pr = nego.profil(p, e, R)
    return {"plafond": f"{nego.euros(pr['plafond'])} par mois ({cfg['marges'][e['position']]:g} % du revenu)",
            "tient à": [R["postes"][x]["court"] for x in pr["indispensables"]],
            "peut renoncer à": [R["postes"][x]["court"] for x in pr["sacrifiables"]]}


def _zone_brute(a, b, cfg):
    R = regles(cfg)
    pa, pb = nego.profil(a, enjeux(a, cfg), R), nego.profil(b, enjeux(b, cfg), R)
    return nego.zone_accord(a, pa, b, pb, R), R


def zone(agents, cfg=None):
    """Options acceptables pour les deux agents (textes), de la plus ambitieuse à la plus modeste."""
    cfg = cfg or normaliser_config()
    if len(agents) != 2:
        return None
    z, R = _zone_brute(agents[0], agents[1], cfg)
    return [nego.texte_option(o, R) for o in z]


def choisir_paire(df, graine, ids=None, cfg=None, exiger_zone=False):
    """Paire « pour / contre » choisie parmi les meilleures (grand écart d'effort).
    Avec exiger_zone, on essaie les graines suivantes jusqu'à une paire qui a une zone d'accord."""
    cfg = cfg or normaliser_config()
    for k in range(200 if exiger_zone else 1):
        try:
            a, b = scene.choisir_paire(df, np.random.default_rng(graine + 7919 * k), ids,
                                       cfg["scenario"], cfg["objectifs"], cfg["eligibilite"])
        except SystemExit as e:               # scene.py arrête le programme : ici, simple erreur
            raise ValueError(str(e)) from None
        if not exiger_zone or _zone_brute(a, b, cfg)[0]:
            return [a, b]
    raise ValueError("Aucune paire automatique n'a de zone d'accord avec ces marges.")


def tirer_groupes(df, n, graine, tirage="opposes", cfg=None):
    """Tire n paires d'agents parmi les éligibles (une paire par scène).

    tirage = "aleatoire"     deux éligibles au hasard, quelle que soit leur position ;
             "opposes"       un « pour » (qui commence) et un « contre » au hasard ;
             "opposes_zone"  idem, mais seulement les paires qui ont une zone d'accord.
    Les paires déjà tirées ne sont pas rejouées tant que c'est possible.
    Renvoie une liste de paires d'identifiants.
    """
    cfg = cfg or normaliser_config()
    el = scene.eligibles(df, cfg["eligibilite"])
    ids = [int(i) for i in el["id"]]
    if len(ids) < 2:
        raise ValueError(f"Il faut au moins 2 agents éligibles (il y en a {len(ids)} avec ce critère).")
    rng = np.random.default_rng(graine)
    pour, contre = [], []
    if tirage != "aleatoire":
        for _, p in el.iterrows():
            pos = enjeux(p, cfg)["position"]
            (pour if pos == "pour" else contre if pos == "contre" else []).append(int(p["id"]))
        if not pour or not contre:
            raise ValueError("Aucune paire « pour / contre » parmi les agents éligibles avec ce "
                             "scénario : choisissez le tirage « tous les éligibles ».")
    candidats = None
    if tirage == "opposes_zone":
        par_id = {int(p["id"]): p for _, p in el.iterrows()}
        candidats = [(i, j) for i in pour for j in contre if _zone_brute(par_id[i], par_id[j], cfg)[0]]
        if not candidats:
            raise ValueError("Aucune paire « pour / contre » n'a de zone d'accord avec ces marges.")

    groupes, vus = [], set()
    for _ in range(n):
        g = None
        for _essai in range(200):
            if candidats is not None:
                g = list(candidats[int(rng.integers(len(candidats)))])
            elif tirage == "opposes":
                g = [int(rng.choice(pour)), int(rng.choice(contre))]
            else:
                g = [int(i) for i in rng.choice(ids, size=2, replace=False)]
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
def _texte(x):
    return x if isinstance(x, (str, int, float, bool, type(None))) else str(x)


def lancer_scene(agents, backend="test", modele=None, base_url=None, tours=12,
                 temperature=0.9, max_tokens=400, sans_reflexion=True, mediateur=True,
                 mode="negociation", config=None, rappel=None, arret=None):
    """Joue une scène et renvoie le dictionnaire décrit en tête de fichier.

    rappel(nom, texte, accord) : appelé après chaque réplique (affichage en direct).
    arret : threading.Event ; s'il est levé, la scène s'interrompt à la réplique suivante.
    """
    t0 = time.perf_counter()
    if mode not in MODES:
        raise ValueError(f"Mode de scène inconnu : {mode}")
    if len(agents) != 2:
        raise ValueError("Une scène réunit exactement deux agents.")
    cfg = config or normaliser_config()
    R = regles(cfg)
    a, b = agents
    noms = [f"{p['prenom']} {p['nom']}" for p in agents]
    ej = [enjeux(p, cfg) for p in agents]
    res = {
        "ids": [int(p["id"]) for p in agents], "noms": noms, "mode": mode,
        "positions": [e["position"] for e in ej],
        "efforts_pct": [e["effort_pct"] for e in ej],
        "backend": backend, "modele": modele or "", "temperature": temperature,
        "max_tokens": max_tokens, "sans_reflexion": sans_reflexion,
        "tours_max": tours, "mediateur_actif": mediateur,
        "config": cfg, "config_id": empreinte(cfg),
        "dialogue": [], "zone": None, "zone_taille": None, "zone_vide": None,
        "accord": None, "accord_signale": None, "proposition_finale": None, "option": None,
        "methode_extraction": None, "coherent": None, "coherent_par_agent": None,
        "position_zone": None, "hausses": None, "plafonds": None,
        "mediateur": False, "tour_syndic": None, "tour_accord": None, "consignes": None,
        "controles": {}, "mal_formees": 0, "duree_s": 0.0, "erreur": None,
    }

    def suivre(nom, texte, accord=False):
        if arret is not None and arret.is_set():
            raise Interrompu("arrêt demandé")
        if rappel:
            rappel(nom, texte, accord)

    try:
        z, _ = _zone_brute(a, b, cfg)
        pa, pb = nego.profil(a, ej[0], R), nego.profil(b, ej[1], R)
        res.update(zone=[nego.texte_option(o, R) for o in z], zone_taille=len(z), zone_vide=not z,
                   plafonds=[round(pa["plafond"]), round(pb["plafond"])])

        client = ClientLLM(backend, modele, base_url, temperature, max_tokens, sans_reflexion)
        if arret is not None and arret.is_set():
            raise Interrompu("arrêt demandé")

        if mode == "negociation":
            dial, infos = nego.jouer(a, b, ej[0], ej[1], client, scene.nettoyer, cfg["scenario"],
                                     tours, mediateur=mediateur, verbeux=False, rappel=suivre, R=R)
            option, methode = nego.extraire_accord(client, dial, infos)
            res["dialogue"] = [list(d) for d in dial]
            res.update(accord_signale=infos["accord_signale"], accord=option is not None,
                       mediateur=infos["syndic"], tour_syndic=infos["tour_syndic"],
                       tour_accord=infos["tour_accord"], consignes=infos["consignes"],
                       methode_extraction=methode)
            if option is not None:
                par_agent = [bool(nego.acceptable(a, pa, option, R)), bool(nego.acceptable(b, pb, option, R))]
                res.update(option={"postes": list(option[0]), "etalement_ans": option[1]},
                           proposition_finale=nego.texte_option(option, R),
                           coherent=all(par_agent), coherent_par_agent=par_agent,
                           position_zone=nego.position_dans_zone(option, z, R),
                           hausses=[round(nego.mensuel(a, *option, R)), round(nego.mensuel(b, *option, R))])
        else:
            dial, _, _ = scene.jouer_scene(a, b, client, tours, scenario=cfg["scenario"], verbeux=False,
                                           objectifs=cfg["objectifs"],
                                           rappel=lambda n, t: suivre(n, t, False))
            res["dialogue"] = [[n, t, False] for n, t in dial]
            res["consignes"] = {noms[0]: scene.consigne(a, b, ej[0], cfg["scenario"], commence=True),
                                noms[1]: scene.consigne(b, a, ej[1], cfg["scenario"])}

        repliques = [(n, t) for n, t, _ in res["dialogue"] if n != nego.SYNDIC]
        res["controles"] = scene.verifier(repliques, a, b) if repliques else {}
        res["mal_formees"] = sum(res["controles"].get(k, 0) for k in ("codes_attributs", "en_tant_que", "mentions_ia"))
    except Interrompu:
        res["erreur"] = "Interrompue"
    except ErreurLLM as e:
        res["erreur"] = f"Modèle : {e}"
    except Exception as e:                    # noqa: BLE001
        res["erreur"] = f"{type(e).__name__} : {e}"
    res["duree_s"] = round(time.perf_counter() - t0, 1)
    return res