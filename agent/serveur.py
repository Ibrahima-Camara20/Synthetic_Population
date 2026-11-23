"""
Labo des agents - Serveur
=========================

Petit serveur web (bibliothèque standard, rien à installer) qui sert la page
labo.html et répond à ses demandes en appelant le code du projet via
adaptateur.py. Les scènes tournent en arrière-plan ; la page suit leur
progression réplique par réplique.

La page envoie avec chaque demande la configuration choisie (scénario,
objectifs, critère d'éligibilité) : le serveur la valide, recalcule les
agents éligibles et leurs enjeux, puis la transmet aux scènes.

Lancement (depuis le dossier agent/) :
    python serveur.py            -> http://localhost:8000
    python serveur.py 8080       -> autre port
"""

import json
import math
import os
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import adaptateur as ad
import journal
import stats

ICI = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(ICI, "labo.html")

COLONNES = ["id", "prenom", "nom", "age_annees", "age", "sexe_fiche", "situation", "foyer_txt",
            "revenu", "revenu_mensuel", "logement", "zone", "tantiemes", "etage", "pieces",
            "ouverture", "conscienciosite", "extraversion", "agreabilite", "nevrosisme",
            "traits", "particularites"]

MODES_AGENTS = ("memes", "optimisees", "opposes", "aleatoire")

# ---------------------------------------------------------------------------
# Population (chargée une fois)
# ---------------------------------------------------------------------------
DF = ad.charger_population()

JOBS = {}                     # id -> état d'une scène ou d'une série en cours
VERROU = threading.Lock()


def propre(x):
    """Rend un objet sérialisable en JSON (numpy, NaN…)."""
    if hasattr(x, "item"):
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
    _, _, enj = ctx
    p = ad.agent(DF, i)
    return {"id": int(i), "nom": f"{p['prenom']} {p['nom']}", "fiche": ad.fiche(p),
            "enjeux": enj.get(int(i)), "marge": ad.marge(p)}


# ---------------------------------------------------------------------------
# Scènes en arrière-plan
# ---------------------------------------------------------------------------
def _executer(job_id, plan, reglages, etiquette, ctx, mode):
    job = JOBS[job_id]
    cfg = ctx[0]
    serie = job_id if len(plan) > 1 else None
    try:
        for k, ids in enumerate(plan):
            agents = [ad.agent(DF, i) for i in ids]
            with VERROU:
                job.update(courante=k, lignes=[], agents=[detail_agent(i, ctx) for i in ids])

            def rappel(l):
                with VERROU:
                    job["lignes"].append(l)

            r = ad.lancer_scene(agents, rappel=rappel, config=cfg, **reglages)
            r["mode_agents"] = mode
            ligne = journal.ajouter(r, serie=serie, etiquette=etiquette)
            with VERROU:
                job["resultats"].append(propre(ligne))
                job["fait"] = k + 1
    except Exception as e:                             # noqa: BLE001
        with VERROU:
            job["erreur_job"] = f"{type(e).__name__} : {e}"
    finally:
        with VERROU:
            job["etat"] = "fini"


def construire_plan(corps, ctx):
    """Liste des groupes d'agents (identifiants) à jouer, un groupe par scène."""
    cfg = ctx[0]
    n = max(1, int(corps.get("n", 1)))
    ids = [int(i) for i in corps.get("ids", [])]
    graine = int(corps.get("graine", 0))
    mode = corps.get("mode_agents") or ("memes" if len(ids) >= 2 else "optimisees")
    if mode not in MODES_AGENTS:
        raise ValueError(f"Mode de tirage inconnu : {mode}")
    taille = 3 if int(corps.get("taille", 2)) == 3 and ad.capacites()["trois_agents"] else 2

    if mode == "memes":
        if len(ids) < 2:
            raise ValueError("Choisissez au moins deux agents, ou un tirage aléatoire.")
        plan = [ids] * n
    elif mode == "optimisees":
        plan = [[int(p["id"]) for p in ad.choisir_paire(DF, graine + k, cfg=cfg)] for k in range(n)]
    else:                                              # « opposes » ou « aleatoire »
        plan = ad.tirer_groupes(DF, n, graine, taille, mode == "opposes", cfg)
    return plan, mode


def lancer(corps):
    r = corps.get("reglages", {})
    reglages = dict(backend=r.get("backend", "test"), modele=r.get("modele") or None,
                    base_url=r.get("base_url") or None, tours=int(r.get("tours", 12)),
                    temperature=float(r.get("temperature", 0.9)),
                    max_tokens=int(r.get("max_tokens", 400)),
                    sans_reflexion=bool(r.get("sans_reflexion", True)),
                    mediateur=bool(r.get("mediateur", True)))
    ctx = contexte(corps.get("config"))
    plan, mode = construire_plan(corps, ctx)
    job_id = uuid.uuid4().hex[:8]
    JOBS[job_id] = {"etat": "en cours", "total": len(plan), "fait": 0, "courante": 0,
                    "lignes": [], "agents": [], "resultats": [], "plan": plan, "mode": mode}
    threading.Thread(target=_executer,
                     args=(job_id, plan, reglages, corps.get("etiquette", ""), ctx, mode),
                     daemon=True).start()
    return {"job": job_id}


def statistiques(q):
    t = journal.tableau()
    if t.empty:
        return {"mesures": {}, "groupes": [], "scenes": [], "filtres": {}}
    filtres = {"modeles": sorted(t["modele_complet"].unique()),
               "etiquettes": sorted(t["etiquette"].fillna("").unique()),
               "series": sorted(t["serie"].dropna().unique())}
    for cle, col in (("modele", "modele_complet"), ("etiquette", "etiquette"), ("serie", "serie")):
        if q.get(cle):
            t = t[t[col].fillna("").isin(q[cle])]
    groupe = [g for g in q.get("groupe", ["modele_complet"]) if g in t.columns]
    cols = ["scene_id", "date", "agents", "modele_complet", "temperature", "etiquette", "serie",
            "scenario_titre", "config_id", "mode_agents",
            "accord", "coherent", "mediateur", "zone_vide", "tour_accord", "repliques",
            "mal_formees", "duree_s", "erreur"]
    return propre({
        "mesures": stats.mesures(t),
        "groupes": stats.par_groupe(t, groupe).to_dict("records") if groupe and not t.empty else [],
        "scenes": t[cols].iloc[::-1].to_dict("records") if not t.empty else [],
        "filtres": filtres,
    })


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
        self.end_headers()
        self.wfile.write(data)

    def _corps(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/labo.html"):
                with open(PAGE, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/api/etat":
                self._json({"capacites": ad.capacites(), "nb_agents": len(DF),
                            "defaut": ad.config_defaut(), "colonnes": ad.colonnes_info(DF)})
            elif u.path == "/api/population":
                self._json(population(contexte()))
            elif u.path.startswith("/api/agent/"):
                self._json(detail_agent(int(u.path.rsplit("/", 1)[1]), contexte()))
            elif u.path.startswith("/api/job/"):
                job = JOBS.get(u.path.rsplit("/", 1)[1])
                with VERROU:
                    self._json(dict(job) if job else {"etat": "inconnu"}, 200 if job else 404)
            elif u.path == "/api/scenes":
                self._json(journal.lire()[::-1])
            elif u.path == "/api/stats":
                self._json(statistiques(q))
            else:
                self._json({"erreur": "introuvable"}, 404)
        except ValueError as e:
            self._json({"erreur": str(e)}, 400)
        except Exception as e:                       # noqa: BLE001
            self._json({"erreur": f"{type(e).__name__} : {e}"}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            corps = self._corps()
            if u.path == "/api/population":
                self._json(population(contexte(corps.get("config"))))
            elif u.path == "/api/agent":
                self._json(detail_agent(int(corps["id"]), contexte(corps.get("config"))))
            elif u.path == "/api/paire":
                cfg = ad.normaliser_config(corps.get("config"))
                ids = [int(p["id"]) for p in ad.choisir_paire(DF, int(corps.get("graine", 0)), cfg=cfg)]
                self._json({"ids": ids})
            elif u.path == "/api/zone":
                agents = [ad.agent(DF, i) for i in corps.get("ids", [])]
                self._json({"zone": ad.zone(agents) if len(agents) >= 2 else None})
            elif u.path == "/api/lancer":
                self._json(lancer(corps))
            elif u.path == "/api/vider":
                journal.vider()
                self._json({"ok": True})
            else:
                self._json({"erreur": "introuvable"}, 404)
        except ValueError as e:                      # configuration ou demande invalide
            self._json({"erreur": str(e)}, 400)
        except Exception as e:                       # noqa: BLE001
            self._json({"erreur": f"{type(e).__name__} : {e}"}, 500)


def main():
    nombres = [a for a in sys.argv[1:] if a.isdigit()]
    port = int(nombres[0]) if nombres else 8000
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
