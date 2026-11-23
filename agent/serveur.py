"""
Labo des agents - Serveur
=========================

Petit serveur web (bibliothèque standard, rien à installer) qui sert la page
labo.html et répond à ses demandes en appelant le code du projet via
adaptateur.py.

Les scènes passent par UNE file d'attente : un seul travail tourne à la fois
(un modèle local ne gagne rien à être sollicité en parallèle, et les mesures
de durée restent comparables). Trois sortes de travaux :

    scene        une scène, agents choisis ;
    serie        N scènes avec les mêmes réglages (agents fixes ou tirés) ;
    experience   N paires d'agents jouées par CHAQUE variante (réglages différents),
                 éventuellement plusieurs fois : la comparaison se fait paire par paire.

Un travail peut être arrêté : il s'interrompt à la réplique suivante.

Lancement (depuis le dossier agent/) :
    python serveur.py            -> http://localhost:8000
    python serveur.py 8080       -> autre port
    python serveur.py --sans-navigateur
"""

import json
import math
import os
import queue
import sys
import threading
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np

import adaptateur as ad
import journal
import stats

ICI = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(ICI, "labo.html")

COLONNES = ["id", "prenom", "nom", "age_annees", "age", "sexe_fiche", "situation", "foyer_txt",
            "revenu", "revenu_mensuel", "logement", "zone", "tantiemes", "etage", "pieces",
            "ouverture", "conscienciosite", "extraversion", "agreabilite", "nevrosisme",
            "traits", "particularites"]

TIRAGES = ("memes", "optimisees", "opposes_zone", "opposes", "aleatoire")
REGLAGES = {"backend": str, "modele": str, "base_url": str, "tours": int, "temperature": float,
            "max_tokens": int, "sans_reflexion": bool, "mediateur": bool, "mode": str}

# ---------------------------------------------------------------------------
# Population (chargée une fois)
# ---------------------------------------------------------------------------
DF = ad.charger_population()

JOBS = {}                     # id -> état d'un travail
VERROU = threading.Lock()
FILE = queue.Queue()


def propre(x):
    """Rend un objet sérialisable en JSON (numpy, NaN…)."""
    if hasattr(x, "item") and not isinstance(x, (list, dict)):
        x = x.item()
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, dict):
        return {str(k): propre(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [propre(v) for v in x]
    return x


def contexte(config=None):
    """Valide la configuration puis calcule les agents éligibles et leurs enjeux.
    Renvoie (config normalisée, ensemble des id éligibles, enjeux par id)."""
    cfg = ad.normaliser_config(config)
    el = ad.eligibles(DF, cfg)
    ids = {int(i) for i in el["id"]}
    enj = {int(p["id"]): ad.enjeux(p, cfg) for _, p in el.iterrows()}
    return cfg, ids, enj


def population(ctx):
    _, ids, enj = ctx
    lignes = []
    for _, p in DF[COLONNES].iterrows():
        d = {c: p[c] for c in COLONNES}
        i = int(p["id"])
        e = enj.get(i)
        d.update(eligible=i in ids, position=e["position"] if e else "",
                 effort_pct=e["effort_pct"] if e else None, mensuel=e["mensuel"] if e else None)
        lignes.append(d)
    return lignes


def detail_agent(i, ctx):
    cfg, ids, enj = ctx
    p = ad.agent(DF, i)
    return {"id": int(i), "nom": f"{p['prenom']} {p['nom']}", "fiche": ad.fiche(p),
            "enjeux": enj.get(int(i)), "marge": ad.marge(p, cfg) if int(i) in ids else None}


def lire_reglages(r, base=None):
    """Réglages du modèle et de la scène, validés (base : valeurs par défaut)."""
    out = dict(base or {"backend": "test", "modele": None, "base_url": None, "tours": 12,
                        "temperature": 0.9, "max_tokens": 400, "sans_reflexion": True,
                        "mediateur": True, "mode": "negociation"})
    for k, typ in REGLAGES.items():
        if k in (r or {}) and r[k] is not None:
            v = r[k]
            out[k] = (v if isinstance(v, bool) else str(v).lower() in ("true", "1", "on")) if typ is bool \
                else (typ(v) if v != "" else None)
    out["modele"] = out["modele"] or None
    out["base_url"] = out["base_url"] or None
    if out["mode"] not in ad.MODES:
        raise ValueError(f"Mode de scène inconnu : {out['mode']}")
    if out["backend"] not in ("test", "ollama", "openai", "anthropic"):
        raise ValueError(f"Backend inconnu : {out['backend']}")
    if not 2 <= out["tours"] <= 60:
        raise ValueError("Le nombre de répliques doit être compris entre 2 et 60.")
    return out


# ---------------------------------------------------------------------------
# Plans : quelles paires jouer
# ---------------------------------------------------------------------------
def paires(corps, cfg, n):
    """n paires d'agents selon le tirage demandé."""
    ids = [int(i) for i in corps.get("ids", [])]
    graine = int(corps.get("graine", 0))
    tirage = corps.get("mode_agents") or ("memes" if len(ids) >= 2 else "optimisees")
    if tirage not in TIRAGES:
        raise ValueError(f"Mode de tirage inconnu : {tirage}")
    if tirage == "memes":
        if len(ids) != 2:
            raise ValueError("Choisissez exactement deux agents, ou un tirage aléatoire.")
        return [ids] * n, tirage
    if tirage == "optimisees":
        return [[int(p["id"]) for p in ad.choisir_paire(DF, graine + k, cfg=cfg)] for k in range(n)], tirage
    return ad.tirer_groupes(DF, n, graine, tirage, cfg), tirage


def construire(corps):
    """Transforme une demande en liste de scènes à jouer : (ids, réglages, config, extra)."""
    sorte = corps.get("sorte", "scene")
    cfg = ad.normaliser_config(corps.get("config"))
    base = lire_reglages(corps.get("reglages"))
    if sorte in ("scene", "serie"):
        n = 1 if sorte == "scene" else max(1, min(500, int(corps.get("n", 10))))
        plan, tirage = paires(corps, cfg, n)
        return [(ids, base, cfg, {"mode_agents": tirage}) for ids in plan], sorte

    if sorte == "experience":
        variantes = corps.get("variantes") or []
        if len(variantes) < 2:
            raise ValueError("Une expérience compare au moins deux variantes.")
        noms = [str(v.get("nom") or f"V{k + 1}").strip() for k, v in enumerate(variantes)]
        if len(set(noms)) != len(noms):
            raise ValueError("Deux variantes ont le même nom.")
        n = max(1, min(200, int(corps.get("n", 10))))
        rep = max(1, min(10, int(corps.get("repetitions", 1))))
        plan, tirage = paires(corps, cfg, n)
        vs = []
        for rang, (nom, v) in enumerate(zip(noms, variantes)):
            r = lire_reglages(v.get("reglages"), base)
            c = ad.normaliser_config({**cfg, "marges": {**cfg["marges"], **(v.get("marges") or {})}})
            vs.append((nom, r, c, {"reglages": {k: r[k] for k in REGLAGES}, "marges": c["marges"]}, rang))
        exp = uuid.uuid4().hex[:6]
        rng = np.random.default_rng(int(corps.get("graine", 0)))
        travaux = []
        for u, ids in enumerate(plan):
            for k in range(rep):
                ordre = rng.permutation(len(vs))          # ordre des variantes tiré au hasard
                for j in ordre:
                    nom, r, c, desc, rang = vs[j]
                    travaux.append((ids, r, c, {"experience": exp, "variante": nom, "variante_rang": rang,
                                                "mode_agents": tirage,
                                                "unite": f"{u + 1}-{k + 1}", "reglages_variante": desc,
                                                "experience_nom": corps.get("nom") or f"Expérience {exp}"}))
        return travaux, sorte
    raise ValueError(f"Sorte de travail inconnue : {sorte}")


# ---------------------------------------------------------------------------
# Travaux en arrière-plan (un seul à la fois)
# ---------------------------------------------------------------------------
def _executer(job_id):
    job = JOBS[job_id]
    if job["arret"].is_set():
        with VERROU:
            job["etat"] = "arrêté"
        return
    with VERROU:
        job["etat"] = "en cours"
    serie = job_id if job["sorte"] != "scene" else None
    try:
        for k, (ids, reg, cfg, extra) in enumerate(job["travaux"]):
            if job["arret"].is_set():
                break
            agents = [ad.agent(DF, i) for i in ids]
            ctx = (cfg, set(ids), {int(p["id"]): ad.enjeux(p, cfg) for p in agents})
            with VERROU:
                job.update(courante=k, lignes=[], agents=[detail_agent(i, ctx) for i in ids],
                           variante=extra.get("variante"))

            def rappel(nom, texte, accord):
                with VERROU:
                    job["lignes"].append([nom, texte, bool(accord)])

            r = ad.lancer_scene(agents, rappel=rappel, config=cfg, arret=job["arret"], **reg)
            ligne = journal.ajouter(r, serie=serie, etiquette=job["etiquette"], **extra)
            with VERROU:
                job["resultats"].append(propre({c: ligne.get(c) for c in RESUME}))
                job["dernier"] = propre(ligne) if job["sorte"] == "scene" else None
                job["fait"] = k + 1
    except Exception as e:                             # noqa: BLE001
        with VERROU:
            job["erreur_job"] = f"{type(e).__name__} : {e}"
    finally:
        with VERROU:
            job["etat"] = "arrêté" if job["arret"].is_set() else "fini"


RESUME = ["scene_id", "noms", "positions", "variante", "unite", "mode", "accord", "coherent", "mediateur",
          "zone_vide", "zone_taille", "proposition_finale", "position_zone", "tour_accord", "duree_s", "erreur"]


def ouvrier():
    while True:
        job_id = FILE.get()
        try:
            _executer(job_id)
        finally:
            FILE.task_done()


def lancer(corps):
    travaux, sorte = construire(corps)
    job_id = uuid.uuid4().hex[:8]
    JOBS[job_id] = {"etat": "en attente", "sorte": sorte, "total": len(travaux), "fait": 0, "courante": 0,
                    "lignes": [], "agents": [], "resultats": [], "dernier": None, "variante": None,
                    "travaux": travaux, "etiquette": corps.get("etiquette", ""),
                    "experience": travaux[0][3].get("experience"), "arret": threading.Event(),
                    "cree": datetime.now().isoformat(timespec="seconds")}
    FILE.put(job_id)
    return {"job": job_id, "total": len(travaux), "en_attente": FILE.qsize() - 1}


def etat_job(job):
    with VERROU:
        d = {k: v for k, v in job.items() if k not in ("travaux", "arret")}
        d["file"] = FILE.qsize()
        return propre(d)


def travaux_actifs():
    with VERROU:
        return [{"job": j, "sorte": v["sorte"], "etat": v["etat"], "fait": v["fait"], "total": v["total"]}
                for j, v in JOBS.items() if v["etat"] in ("en attente", "en cours")]


# ---------------------------------------------------------------------------
# Statistiques et expériences
# ---------------------------------------------------------------------------
GROUPES_AUTORISES = ["modele_complet", "temperature", "etiquette", "tours_max", "mediateur_actif", "serie",
                     "scenario_titre", "config_id", "mode_agents", "mode", "variante", "experience"]


def statistiques(q):
    t = journal.tableau()
    if t.empty:
        return {"mesures": {}, "groupes": [], "scenes": [], "filtres": {}}
    filtres = {"modeles": sorted(t["modele_complet"].unique()),
               "etiquettes": sorted(t["etiquette"].fillna("").unique()),
               "modes": sorted(t["mode"].fillna("").unique()),
               "series": sorted(t["serie"].dropna().unique())}
    for cle, col in (("modele", "modele_complet"), ("etiquette", "etiquette"), ("serie", "serie"),
                     ("mode", "mode")):
        if q.get(cle):
            t = t[t[col].fillna("").isin(q[cle])]
    groupe = [g for g in q.get("groupe", ["modele_complet"]) if g in GROUPES_AUTORISES and g in t.columns]
    cols = ["scene_id", "date", "agents", "mode", "modele_complet", "temperature", "etiquette", "serie",
            "experience", "variante", "scenario_titre", "config_id", "mode_agents",
            "accord", "coherent", "mediateur", "zone_vide", "zone_taille", "position_zone", "tour_accord",
            "repliques", "mal_formees", "duree_s", "erreur", "proposition_finale"]
    return propre({
        "mesures": stats.mesures(t) if not t.empty else {},
        "groupes": stats.par_groupe(t, groupe) if not t.empty else [],
        "scenes": t[cols].iloc[::-1].to_dict("records") if not t.empty else [],
        "filtres": filtres,
    })


def experiences():
    t = journal.tableau()
    if t.empty or t["experience"].isna().all():
        return []
    out = []
    for e, g in t[t["experience"].notna()].groupby("experience"):
        out.append({"experience": e, "nom": g["experience_nom"].iloc[0] if "experience_nom" in g else e,
                    "date": g["date"].min(), "scenes": int(len(g)),
                    "variantes": list(dict.fromkeys(g.sort_values(["variante_rang", "date"])["variante"])),
                    "unites": int(g["unite"].nunique())})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def experience(e):
    t = journal.tableau()
    if t.empty:
        raise ValueError("Journal vide.")
    g = t[t["experience"] == e]
    if g.empty:
        raise ValueError(f"Expérience inconnue : {e}")
    return propre({"experience": e, "nom": g["experience_nom"].iloc[0] if "experience_nom" in g else e,
                   **stats.resume_experience(g)})


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Gestionnaire(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(propre(obj), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _corps(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _erreurs(self, f):
        try:
            f()
        except ValueError as e:                      # configuration ou demande invalide
            self._json({"erreur": str(e)}, 400)
        except Exception as e:                       # noqa: BLE001
            self._json({"erreur": f"{type(e).__name__} : {e}"}, 500)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        self._erreurs(lambda: self._get(u, q))

    def _get(self, u, q):
        if u.path in ("/", "/labo.html"):
            with open(PAGE, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif u.path == "/api/etat":
            self._json({"nb_agents": len(DF), "defaut": ad.config_defaut(), "modes": list(ad.MODES),
                        "colonnes": ad.colonnes_info(DF), "travaux": travaux_actifs()})
        elif u.path.startswith("/api/job/"):
            job = JOBS.get(u.path.rsplit("/", 1)[1])
            self._json(etat_job(job) if job else {"etat": "inconnu"}, 200 if job else 404)
        elif u.path == "/api/scenes":
            self._json(journal.lire()[::-1])
        elif u.path == "/api/stats":
            self._json(statistiques(q))
        elif u.path == "/api/experiences":
            self._json(experiences())
        elif u.path.startswith("/api/experience/"):
            self._json(experience(u.path.rsplit("/", 1)[1]))
        else:
            self._json({"erreur": "introuvable"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        self._erreurs(lambda: self._post(u, self._corps()))

    def _post(self, u, corps):
        if u.path == "/api/population":
            self._json(population(contexte(corps.get("config"))))
        elif u.path == "/api/agent":
            self._json(detail_agent(int(corps["id"]), contexte(corps.get("config"))))
        elif u.path == "/api/paire":
            cfg = ad.normaliser_config(corps.get("config"))
            ids = [int(p["id"]) for p in ad.choisir_paire(DF, int(corps.get("graine", 0)), cfg=cfg,
                                                          exiger_zone=bool(corps.get("exiger_zone")))]
            self._json({"ids": ids})
        elif u.path == "/api/zone":
            cfg = ad.normaliser_config(corps.get("config"))
            agents = [ad.agent(DF, i) for i in corps.get("ids", [])]
            self._json({"zone": ad.zone(agents, cfg) if len(agents) == 2 else None})
        elif u.path == "/api/lancer":
            self._json(lancer(corps))
        elif u.path.startswith("/api/arreter/"):
            job = JOBS.get(u.path.rsplit("/", 1)[1])
            if not job:
                raise ValueError("Travail inconnu.")
            job["arret"].set()
            self._json({"ok": True})
        elif u.path == "/api/vider":
            journal.vider()
            self._json({"ok": True})
        else:
            self._json({"erreur": "introuvable"}, 404)


def main():
    nombres = [a for a in sys.argv[1:] if a.isdigit()]
    port = int(nombres[0]) if nombres else 8000
    threading.Thread(target=ouvrier, daemon=True).start()
    serveur = ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire)
    url = f"http://localhost:{port}"
    print(f"Labo des agents : {url}   (Ctrl+C pour arrêter)")
    if "--sans-navigateur" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    main()