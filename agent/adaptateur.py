"""
Labo des agents - Adaptateur
============================

Le SEUL fichier du labo qui touche au code du projet (scene.py, negociation.py,
personas.py, llm.py). Les appels sont explicites : si une fonction du projet
change de nom ou de signature, c'est ici qu'on corrige ; serveur.py, journal.py
et stats.py ne changent pas.

Deux ou trois agents par scène en négociation (le débat se joue à deux).

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
    propositions, concessions              proposition de chaque réplique ; chemin fait par chaque agent
    chiffres, juge, valide                 montants inventés ; notes du juge ; scène crédible ou non
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

import juge                            # noqa: E402
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


def _zone_groupe(agents, cfg):
    R = regles(cfg)
    profils = [nego.profil(p, enjeux(p, cfg), R) for p in agents]
    return nego.zone_groupe(agents, profils, R), R


def _zone_brute(a, b, cfg):
    return _zone_groupe([a, b], cfg)


def zone(agents, cfg=None):
    """Options acceptables pour tous les agents (textes), de la plus ambitieuse à la plus modeste."""
    cfg = cfg or normaliser_config()
    if len(agents) < 2:
        return None
    z, R = _zone_groupe(list(agents), cfg)
    return [nego.texte_option(o, R) for o in z]


def _tiers(df, a, b, cfg, rng, exiger_zone):
    """Un troisième agent pour la paire (a, b) : de préférence « partagé », sinon n'importe quel éligible."""
    el = scene.eligibles(df, cfg["eligibilite"])
    candidats = [p for _, p in el.iterrows() if int(p["id"]) not in (int(a["id"]), int(b["id"]))]
    partages = [p for p in candidats if enjeux(p, cfg)["position"] == "partage"]
    for groupe in (partages, candidats):
        ordre = rng.permutation(len(groupe))
        for k in ordre:
            c = groupe[int(k)]
            if not exiger_zone or _zone_groupe([a, b, c], cfg)[0]:
                return c
    return None


def choisir_paire(df, graine, ids=None, cfg=None, exiger_zone=False, taille=2):
    """Paire « pour / contre » choisie parmi les meilleures (grand écart d'effort), plus un
    troisième agent (de préférence « partagé ») si taille = 3. Avec exiger_zone, on essaie les
    graines suivantes jusqu'à un groupe qui a une zone d'accord."""
    cfg = cfg or normaliser_config()
    for k in range(200 if exiger_zone else 1):
        rng = np.random.default_rng(graine + 7919 * k)
        try:
            a, b = scene.choisir_paire(df, rng, ids, cfg["scenario"], cfg["objectifs"], cfg["eligibilite"])
        except SystemExit as e:               # scene.py arrête le programme : ici, simple erreur
            raise ValueError(str(e)) from None
        groupe = [a, b]
        if taille == 3:
            c = _tiers(df, a, b, cfg, rng, exiger_zone)
            if c is None:
                continue
            groupe.append(c)
        if not exiger_zone or _zone_groupe(groupe, cfg)[0]:
            return groupe
    raise ValueError("Aucun groupe automatique n'a de zone d'accord avec ces marges.")


def tirer_groupes(df, n, graine, tirage="opposes", cfg=None, taille=2):
    """Tire n groupes d'agents parmi les éligibles (un groupe par scène).

    tirage = "aleatoire"     des éligibles au hasard, quelle que soit leur position ;
             "opposes"       un « pour » (qui commence), un « contre » (et un troisième agent) ;
             "opposes_zone"  idem, mais seulement les groupes qui ont une zone d'accord.
    taille = 2 ou 3. Avec 3, le troisième est de préférence « partagé ».
    Les groupes déjà tirés ne sont pas rejoués tant que c'est possible.
    Renvoie une liste de listes d'identifiants.
    """
    cfg = cfg or normaliser_config()
    el = scene.eligibles(df, cfg["eligibilite"])
    ids = [int(i) for i in el["id"]]
    if len(ids) < taille:
        raise ValueError(f"Il faut au moins {taille} agents éligibles (il y en a {len(ids)} avec ce critère).")
    rng = np.random.default_rng(graine)
    par_id = {int(p["id"]): p for _, p in el.iterrows()}
    pos = {i: enjeux(p, cfg)["position"] for i, p in par_id.items()}
    pour = [i for i, v in pos.items() if v == "pour"]
    contre = [i for i, v in pos.items() if v == "contre"]
    partage = [i for i, v in pos.items() if v == "partage"]
    if tirage != "aleatoire" and (not pour or not contre):
        raise ValueError("Aucune paire « pour / contre » parmi les agents éligibles avec ce "
                         "scénario : choisissez le tirage « tous les éligibles ».")

    def un_groupe():
        if tirage == "aleatoire":
            return [int(i) for i in rng.choice(ids, size=taille, replace=False)]
        g = [int(rng.choice(pour)), int(rng.choice(contre))]
        if taille == 3:
            reste = [i for i in (partage or ids) if i not in g] or [i for i in ids if i not in g]
            g.append(int(rng.choice(reste)))
        return g

    def a_zone(g):
        return bool(_zone_groupe([par_id[i] for i in g], cfg)[0])

    groupes, vus = [], set()
    for _ in range(n):
        g = None
        for essai in range(600):
            g = un_groupe()
            if tirage == "opposes_zone" and not a_zone(g):
                g = None
                continue
            if frozenset(g) not in vus or essai > 400:
                break
        if g is None:
            raise ValueError("Aucun groupe « pour / contre » n'a de zone d'accord avec ces marges.")
        vus.add(frozenset(g))
        groupes.append(g)
    return groupes


def fiche(p):
    return personas.texte_fiche(p)


# ---------------------------------------------------------------------------
# Lancer une scène
# ---------------------------------------------------------------------------
def lancer_scene(agents, backend="test", modele=None, base_url=None, tours=12,
                 temperature=0.9, max_tokens=400, sans_reflexion=True, mediateur=True,
                 mode="negociation", config=None, rappel=None, arret=None,
                 juger=False, modele_juge=None):
    """Joue une scène et renvoie le dictionnaire décrit en tête de fichier.

    rappel(nom, texte, accord) : appelé après chaque réplique (affichage en direct).
    arret : threading.Event ; s'il est levé, la scène s'interrompt à la réplique suivante.
    juger : faire noter la scène par le juge (un appel de plus au modèle, ou à modele_juge).
    """
    t0 = time.perf_counter()
    agents = list(agents)
    if mode not in MODES:
        raise ValueError(f"Mode de scène inconnu : {mode}")
    if mode == "debat" and len(agents) != 2:
        raise ValueError("Le débat se joue à deux agents.")
    if not 2 <= len(agents) <= 3:
        raise ValueError("Une scène réunit deux ou trois agents.")
    cfg = config or normaliser_config()
    R = regles(cfg)
    noms = [f"{p['prenom']} {p['nom']}" for p in agents]
    ej = [enjeux(p, cfg) for p in agents]
    res = {
        "ids": [int(p["id"]) for p in agents], "noms": noms, "mode": mode, "taille": len(agents),
        "positions": [e["position"] for e in ej],
        "efforts_pct": [e["effort_pct"] for e in ej],
        "backend": backend, "modele": modele or "", "temperature": temperature,
        "max_tokens": max_tokens, "sans_reflexion": sans_reflexion,
        "tours_max": tours, "mediateur_actif": mediateur,
        "config": cfg, "config_id": empreinte(cfg),
        "dialogue": [], "zone": None, "zone_taille": None, "zone_vide": None,
        "accord": None, "accord_signale": None, "proposition_finale": None, "option": None,
        "methode_extraction": None, "coherent": None, "coherent_par_agent": None,
        "position_zone": None, "hausses": None, "plafonds": None, "zone_couts": None,
        "propositions": None, "methode_propositions": None, "concessions": None,
        "chiffres": None, "juge": None, "valide": None,
        "mediateur": False, "tour_syndic": None, "tour_accord": None, "consignes": None,
        "controles": {}, "mal_formees": 0, "duree_s": 0.0, "erreur": None,
    }

    def suivre(nom, texte, accord=False):
        if arret is not None and arret.is_set():
            raise Interrompu("arrêt demandé")
        if rappel:
            rappel(nom, texte, accord)

    try:
        z, _ = _zone_groupe(agents, cfg)
        profils = [nego.profil(p, e, R) for p, e in zip(agents, ej)]
        res.update(zone=[nego.texte_option(o, R) for o in z], zone_taille=len(z), zone_vide=not z,
                   plafonds=[round(pr["plafond"]) for pr in profils],
                   zone_couts=[round(min(nego.cout_annuel(o, R) for o in z)),
                               round(max(nego.cout_annuel(o, R) for o in z))] if z else None)

        client = ClientLLM(backend, modele, base_url, temperature, max_tokens, sans_reflexion)
        if arret is not None and arret.is_set():
            raise Interrompu("arrêt demandé")

        if mode == "negociation":
            dial, infos = nego.jouer_groupe(agents, ej, client, scene.nettoyer, cfg["scenario"], tours,
                                            mediateur=mediateur, verbeux=False, rappel=suivre, R=R)
            res["dialogue"] = [list(d) for d in dial]
            option, methode = nego.extraire_accord(client, dial, infos)
            res.update(accord_signale=infos["accord_signale"], accord=option is not None,
                       mediateur=infos["syndic"], tour_syndic=infos["tour_syndic"],
                       tour_accord=infos["tour_accord"], consignes=infos["consignes"],
                       methode_extraction=methode)
            if option is not None:
                par_agent = [bool(nego.acceptable(p, pr, option, R)) for p, pr in zip(agents, profils)]
                res.update(option={"postes": list(option[0]), "etalement_ans": option[1]},
                           proposition_finale=nego.texte_option(option, R),
                           coherent=all(par_agent), coherent_par_agent=par_agent,
                           position_zone=nego.position_dans_zone(option, z, R),
                           hausses=[round(nego.mensuel(p, *option, R)) for p in agents])
            # Qui a proposé quoi, et qui a cédé
            props, methode_p = nego.suivre_propositions(client, dial)
            res.update(propositions=[None if o is None else {"postes": list(o[0]), "etalement_ans": o[1],
                                                             "cout_annuel": round(nego.cout_annuel(o, R))}
                                     for o in props],
                       methode_propositions=methode_p,
                       concessions=nego.concessions(agents, ej, dial, props, R, option))
        else:
            a, b = agents
            dial, _, _ = scene.jouer_scene(a, b, client, tours, scenario=cfg["scenario"], verbeux=False,
                                           objectifs=cfg["objectifs"],
                                           rappel=lambda n, t: suivre(n, t, False))
            res["dialogue"] = [[n, t, False] for n, t in dial]
            res["consignes"] = {noms[0]: scene.consigne(a, b, ej[0], cfg["scenario"], commence=True),
                                noms[1]: scene.consigne(b, a, ej[1], cfg["scenario"])}

        repliques = [(n, t) for n, t, _ in res["dialogue"] if n != nego.SYNDIC]
        if len(agents) == 2 and repliques:
            res["controles"] = scene.verifier(repliques, agents[0], agents[1])
        elif repliques:
            res["controles"] = _controles_groupe(repliques, agents)
        res["mal_formees"] = sum(res["controles"].get(k, 0) for k in ("codes_attributs", "en_tant_que", "mentions_ia"))
        res["chiffres"] = juge.verifier_chiffres(res["dialogue"], agents, ej, R)
        if juger and res["dialogue"]:
            try:
                cj = ClientLLM(backend, modele_juge or modele, base_url, 0.2, 600, sans_reflexion)
                res["juge"] = juge.juger(cj, res["dialogue"], agents, cfg["scenario"])
            except Exception as e:                # noqa: BLE001  le juge ne doit pas faire échouer la scène
                res["juge"] = {"erreur": f"{type(e).__name__} : {e}"}
        res["valide"] = juge.valide(res["chiffres"], res["juge"] if res["juge"] and "erreur" not in res["juge"] else None)
    except Interrompu:
        res["erreur"] = "Interrompue"
    except ErreurLLM as e:
        res["erreur"] = f"Modèle : {e}"
    except Exception as e:                    # noqa: BLE001
        res["erreur"] = f"{type(e).__name__} : {e}"
    res["duree_s"] = round(time.perf_counter() - t0, 1)
    return res


def _controles_groupe(repliques, agents):
    """Contrôles de forme pour une scène à plus de deux (scene.verifier est écrit pour deux)."""
    textes = [t for _, t in repliques]
    tout = " ".join(textes).lower()
    return {"repliques": len(textes),
            "longueur_moyenne_mots": round(sum(len(t.split()) for t in textes) / len(textes), 1),
            "codes_attributs": len(re.findall(r"\bA\d{1,2}\b", " ".join(textes))),
            "en_tant_que": tout.count("en tant que"),
            "mentions_ia": len(re.findall(r"\b(ia|intelligence artificielle|mod[eè]le de langage)\b", tout))}


def juger_scene(ligne, df, backend, modele=None, base_url=None, sans_reflexion=True):
    """Évalue après coup une scène du journal (avec le modèle donné)."""
    agents = [agent(df, i) for i in ligne["ids"]]
    cfg = ligne.get("config") or normaliser_config()
    client = ClientLLM(backend, modele, base_url, 0.2, 600, sans_reflexion)
    dial = [d if isinstance(d, (list, tuple)) else [d["locuteur"], d["texte"], False] for d in ligne["dialogue"]]
    ev = juge.juger(client, dial, agents, cfg["scenario"])
    R = regles(normaliser_config(cfg))
    chiffres = ligne.get("chiffres") or juge.verifier_chiffres(dial, agents, [enjeux(p, normaliser_config(cfg)) for p in agents], R)
    return {**ev, "chiffres": chiffres, "valide": juge.valide(chiffres, ev)}