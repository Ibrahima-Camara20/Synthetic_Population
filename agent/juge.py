"""
Labo des agents - Le juge
=========================

Un accord ne vaut que si la scène est crédible. Deux contrôles :

1. Les CHIFFRES (mécanique, gratuit, toujours fait) : chaque montant en euros cité
   dans la scène est comparé aux montants réels (hausse mensuelle de chaque option
   pour chaque agent, coût des postes et des options, budget, revenus, plafonds). Un
   montant qui ne correspond à aucun d'eux (à 2 % près) est compté comme « inventé ».
   Les montants réels sont nombreux (surtout entre 10 et 500 €) : ce contrôle repère
   les chiffres manifestement faux, pas toutes les erreurs ; le juge complète.

2. Le JUGE (un appel au modèle, optionnel) : il lit les fiches et la scène et note
   de 1 à 5 :
     fidelite   chaque agent joue-t-il bien sa fiche (situation, personnalité) ?
     coherence  les positions et les concessions se suivent-elles logiquement ?
     naturel    est-ce une conversation crédible entre voisins ?
   et écrit un commentaire d'une ou deux phrases.

Une scène est dite VALIDE si aucun montant n'est inventé et, quand elle a été jugée,
si la fidélité moyenne et la cohérence valent au moins 3.

Les évaluations sont rangées à part, dans scenes/juges.jsonl (le journal des scènes
n'est jamais réécrit) : une scène peut être jugée plus tard, ou rejugée par un autre modèle.
"""

import json
import os
import re
import threading
from datetime import datetime

import negociation as nego
import personas

ICI = os.path.dirname(os.path.abspath(__file__))
CHEMIN = os.path.join(ICI, "scenes", "juges.jsonl")
_VERROU = threading.Lock()
SEUIL = 3
TOLERANCE = 0.02          # un montant arrondi à 2 % près est accepté


# ---------------------------------------------------------------------------
# 1. Les chiffres
# ---------------------------------------------------------------------------
MONTANT = re.compile(r"(\d{1,3}(?:[  \xa0.]\d{3})+|\d+)(?:[,.](\d{1,2}))?\s*(?:€|euros?\b)", re.I)


def montants(texte):
    out = []
    for m in MONTANT.finditer(texte):
        entier = re.sub(r"[  \xa0.]", "", m.group(1))
        out.append(float(entier + ("." + m.group(2) if m.group(2) else "")))
    return out


def montants_reels(agents, enjeux, R):
    """Tous les montants qu'un agent peut citer à bon droit."""
    vrais = set()
    for v in R["postes"].values():
        vrais.add(v["cout"])
    vrais.add(sum(v["cout"] for v in R["postes"].values()))
    for p, e in zip(agents, enjeux):
        for o in nego.options(R):
            vrais.add(nego.mensuel(p, *o, R))                     # hausse mensuelle de chaque option
            vrais.add(nego.cout_option(o, R) / o[1])              # coût annuel du projet
            vrais.add(nego.cout_option(o, R))                     # coût total de l'option
        for k in R["postes"]:
            vrais.add(nego.mensuel(p, [k], 1, R))
        vrais.update([p["revenu_mensuel"], e.get("part_annuelle", 0), e.get("mensuel", 0),
                      nego.profil(p, e, R)["plafond"]])
    return sorted(x for x in vrais if x)


def verifier_chiffres(dialogue, agents, enjeux, R):
    """{"montants": n, "inventes": k, "exemples": [...]} ; on ignore les montants < 5 €
    et ceux du syndic (calculés par le programme)."""
    vrais = montants_reels(agents, enjeux, R)
    cites, inventes = 0, []
    for nom, texte, *_ in dialogue:
        if nom == nego.SYNDIC:
            continue
        for x in montants(texte):
            if x < 5:
                continue
            cites += 1
            if not any(abs(x - v) <= max(1.0, TOLERANCE * v) for v in vrais):
                inventes.append(f"{nom.split(' ')[0]} : {x:g} €")
    return {"montants": cites, "inventes": len(inventes), "exemples": inventes[:6]}


# ---------------------------------------------------------------------------
# 2. Le juge (un appel au modèle)
# ---------------------------------------------------------------------------
def _consigne_juge():
    return ("Tu es un évaluateur exigeant de scènes de théâtre jouées par des agents conversationnels. "
            "Tu notes la qualité du jeu, pas le résultat de la négociation. Tu réponds uniquement en JSON.")


def juger(client, dialogue, agents, scenario):
    """Notes du juge. Lève ValueError si la réponse est inexploitable."""
    noms = [f"{p['prenom']} {p['nom']}" for p in agents]
    if client.backend == "test":                                 # notes scriptées pour tester la chaîne
        return {"fidelite": {n: 4 for n in noms}, "coherence": 4, "naturel": 3,
                "commentaire": "Évaluation de test : la chaîne du juge fonctionne.", "juge": "test"}
    fiches = "\n\n".join(f"### {n}\n{personas.texte_fiche(p)}" for n, p in zip(noms, agents))
    scene = "\n".join(f"{n} : {t}" for n, t, *_ in dialogue)
    question = f"""LE CONTEXTE
{scenario.get('lieu', '')}. Des copropriétaires négocient des travaux.

LES FICHES DES PERSONNAGES
{fiches}

LA SCÈNE
{scene}

Note de 1 (très mauvais) à 5 (excellent) :
- fidelite : pour CHAQUE personnage, joue-t-il sa fiche (situation, moyens, personnalité) ?
- coherence : les positions, propositions et concessions se suivent-elles logiquement ?
- naturel : est-ce une conversation crédible entre voisins (ton, longueur, pas de récitation) ?

Réponds en JSON, sans rien d'autre :
{{"fidelite": {{{", ".join(f'"{n}": note' for n in noms)}}}, "coherence": note, "naturel": note,
"commentaire": "une ou deux phrases sur le principal défaut ou la principale qualité"}}"""
    brut = client.repondre(_consigne_juge(), [{"role": "user", "content": question}])
    brut = re.sub(r"<think>.*?(</think>|$)", "", brut, flags=re.S)
    m = re.search(r"\{.*\}", brut, re.S)
    if not m:
        raise ValueError("Le juge n'a pas répondu en JSON.")
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise ValueError("Le juge a répondu un JSON illisible.") from None

    def note(x):
        try:
            return max(1, min(5, int(round(float(x)))))
        except (TypeError, ValueError):
            return None
    fid = d.get("fidelite") or {}
    fid = {n: note(fid.get(n, fid.get(n.split(" ")[0]))) for n in noms} if isinstance(fid, dict) \
        else {n: note(fid) for n in noms}
    res = {"fidelite": fid, "coherence": note(d.get("coherence")), "naturel": note(d.get("naturel")),
           "commentaire": str(d.get("commentaire", ""))[:400],
           "juge": f"{client.backend} {client.modele or ''}".strip()}
    if res["coherence"] is None or not any(v is not None for v in fid.values()):
        raise ValueError("Le juge n'a pas donné de notes exploitables.")
    return res


def valide(chiffres, juge=None):
    """Scène valide : aucun montant inventé et, si elle a été jugée, fidélité et cohérence ≥ 3."""
    if chiffres and chiffres.get("inventes", 0) > 0:
        return False
    if juge:
        fid = [v for v in (juge.get("fidelite") or {}).values() if v is not None]
        if (fid and sum(fid) / len(fid) < SEUIL) or (juge.get("coherence") or 5) < SEUIL:
            return False
    return True


# ---------------------------------------------------------------------------
# Rangement des évaluations
# ---------------------------------------------------------------------------
def enregistrer(scene_id, evaluation):
    os.makedirs(os.path.dirname(CHEMIN), exist_ok=True)
    ligne = {"scene_id": scene_id, "date": datetime.now().isoformat(timespec="seconds"), **evaluation}
    with _VERROU, open(CHEMIN, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def lire():
    """Dernière évaluation de chaque scène : {scene_id: évaluation}."""
    if not os.path.exists(CHEMIN):
        return {}
    out = {}
    with _VERROU, open(CHEMIN, encoding="utf-8") as f:
        for l in f:
            try:
                d = json.loads(l)
                out[d["scene_id"]] = d
            except (json.JSONDecodeError, KeyError):
                pass
    return out