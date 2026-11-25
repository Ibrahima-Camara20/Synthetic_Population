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
import juge
import stats
import voix

ICI = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(ICI, "labo.html")

COLONNES = ["id", "prenom", "nom", "age_annees", "age", "sexe_fiche", "situation", "foyer_txt",
            "revenu", "revenu_mensuel", "logement", "zone", "tantiemes", "etage", "pieces",
            "ouverture", "conscienciosite", "extraversion", "agreabilite", "nevrosisme",
            "traits", "particularites"]

TIRAGES = ("memes", "optimisees", "opposes_zone", "opposes", "aleatoire")
REGLAGES = {"backend": str, "modele": str, "base_url": str, "tours": int, "temperature": float,
            "max_tokens": int, "sans_reflexion": bool, "mediateur": bool, "mode": str,
            "taille": int, "juger": bool, "modele_juge": str}

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
                        "mediateur": True, "mode": "negociation", "taille": 2, "juger": False,
                        "modele_juge": None})
    for k, typ in REGLAGES.items():
        if k in (r or {}) and r[k] is not None:
            v = r[k]
            out[k] = (v if isinstance(v, bool) else str(v).lower() in ("true", "1", "on")) if typ is bool \
                else (typ(v) if v != "" else None)
    out["modele"] = out["modele"] or None
    out["base_url"] = out["base_url"] or None
    out["modele_juge"] = out["modele_juge"] or None
    if out["taille"] not in (2, 3):
        raise ValueError("Une scène réunit deux ou trois agents.")
    if out["mode"] == "debat" and out["taille"] != 2:
        raise ValueError("Le débat se joue à deux agents : choisissez la négociation pour une scène à trois.")
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
def paires(corps, cfg, n, taille=2):
    """n groupes de `taille` agents selon le tirage demandé."""
    ids = [int(i) for i in corps.get("ids", [])]
    graine = int(corps.get("graine", 0))
    tirage = corps.get("mode_agents") or ("memes" if len(ids) >= 2 else "optimisees")
    if tirage not in TIRAGES:
        raise ValueError(f"Mode de tirage inconnu : {tirage}")
    if tirage == "memes":
        if len(ids) != taille:
            raise ValueError(f"Choisissez exactement {taille} agents, ou un tirage aléatoire.")
        return [ids] * n, tirage
    if tirage == "optimisees":
        return [[int(p["id"]) for p in ad.choisir_paire(DF, graine + k, cfg=cfg, taille=taille,
                                                        exiger_zone=taille == 3)]
                for k in range(n)], tirage
    return ad.tirer_groupes(DF, n, graine, tirage, cfg, taille), tirage


def construire(corps):
    """Transforme une demande en liste de scènes à jouer : (ids, réglages, config, extra)."""
    sorte = corps.get("sorte", "scene")
    cfg = ad.normaliser_config(corps.get("config"))
    base = lire_reglages(corps.get("reglages"))
    if sorte in ("scene", "serie"):
        n = 1 if sorte == "scene" else max(1, min(500, int(corps.get("n", 10))))
        plan, tirage = paires(corps, cfg, n, base["taille"])
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
        vs = []
        for rang, (nom, v) in enumerate(zip(noms, variantes)):
            r = lire_reglages(v.get("reglages"), base)
            c = ad.normaliser_config({**cfg, "marges": {**cfg["marges"], **(v.get("marges") or {})}})
            vs.append((nom, r, c, {"reglages": {k: r[k] for k in REGLAGES}, "marges": c["marges"]}, rang))
        # Les groupes sont tirés à la taille maximale ; une variante à deux agents garde les deux premiers
        # (le « pour » et le « contre ») : la comparaison 2 contre 3 reste appariée.
        plan, tirage = paires(corps, cfg, n, max(v[1]["taille"] for v in vs))
        exp = uuid.uuid4().hex[:6]
        rng = np.random.default_rng(int(corps.get("graine", 0)))
        travaux = []
        for u, ids in enumerate(plan):
            for k in range(rep):
                ordre = rng.permutation(len(vs))          # ordre des variantes tiré au hasard
                for j in ordre:
                    nom, r, c, desc, rang = vs[j]
                    travaux.append((ids[:r["taille"]], r, c, {"experience": exp, "variante": nom, "variante_rang": rang,
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

            r = ad.lancer_scene(agents, rappel=rappel, config=cfg, arret=job["arret"],
                                **{k: v for k, v in reg.items() if k != "taille"})
            ligne = journal.ajouter(r, serie=serie, etiquette=job["etiquette"], **extra)
            if r.get("juge") and "erreur" not in r["juge"]:
                juge.enregistrer(ligne["scene_id"], {**r["juge"], "chiffres": r["chiffres"], "valide": r["valide"]})
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


RESUME = ["scene_id", "noms", "positions", "variante", "unite", "mode", "taille", "accord", "coherent", "mediateur",
          "zone_vide", "zone_taille", "proposition_finale", "position_zone", "tour_accord", "valide", "duree_s", "erreur"]


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
GROUPES_AUTORISES = ["modele_complet", "taille", "valide", "temperature", "etiquette", "tours_max", "mediateur_actif", "serie",
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
    cols = ["scene_id", "date", "agents", "mode", "taille", "valide", "juge_fidelite", "juge_coherence",
            "chiffres_inventes", "modele_complet", "temperature", "etiquette", "serie",
            "experience", "variante", "scenario_titre", "config_id", "mode_agents",
            "accord", "coherent", "mediateur", "zone_vide", "zone_taille", "position_zone", "tour_accord",
            "repliques", "mal_formees", "duree_s", "erreur", "proposition_finale"]
    return propre({
        "mesures": stats.mesures(t) if not t.empty else {},
        "concessions": stats.concessions_par_position(t) if not t.empty else [],
        "groupes": stats.par_groupe(t, groupe) if not t.empty else [],
        "scenes": t[cols].iloc[::-1].to_dict("records") if not t.empty else [],
        "filtres": filtres,
    })


def analyses():
    t = journal.tableau()
    if t.empty:
        return {"lignes": [], "correlations": [], "concessions": []}
    return propre(stats.analyse(t, DF))


def juger_apres_coup(scene_id, corps):
    s = _scene(scene_id)
    reg = lire_reglages(corps.get("reglages"))
    ev = ad.juger_scene(s, DF, reg["backend"], reg["modele_juge"] or reg["modele"], reg["base_url"],
                        reg["sans_reflexion"])
    return juge.enregistrer(scene_id, ev)


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
# État du modèle (indicateur de la barre latérale)
# ---------------------------------------------------------------------------
def etat_modele(backend, modele=None, base_url=None):
    """Vérifie, sans lancer de scène, que le modèle choisi est joignable."""
    import urllib.request
    if backend == "test":
        return {"ok": True, "message": "Mode test : répliques scriptées, sans modèle."}
    if backend == "ollama":
        base = (base_url or "http://localhost:11434").rstrip("/")
        base = base[:-3] if base.endswith("/v1") else base
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=2) as r:
                noms = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
        except Exception:                                        # noqa: BLE001
            return {"ok": False, "message": "Ollama ne répond pas. Lancez l'application Ollama, puis réessayez."}
        if modele and modele not in noms and f"{modele}:latest" not in noms:
            return {"ok": False, "message": f"Le modèle {modele} n'est pas installé. Modèles disponibles : "
                                            + (", ".join(noms) or "aucun") + "."}
        return {"ok": True, "message": f"Ollama répond, {modele or 'modèle'} est installé.", "modeles": noms}
    cles = {"openai": ("LLM_API_KEY", "OPENAI_API_KEY"), "anthropic": ("LLM_API_KEY", "ANTHROPIC_API_KEY")}
    if not any(os.environ.get(c) for c in cles.get(backend, ())):
        return {"ok": False, "message": f"Aucune clé trouvée. Définissez {cles[backend][1]} dans le terminal "
                                        "avant de lancer le serveur."}
    return {"ok": True, "message": "Clé d'API trouvée dans l'environnement."}


# ---------------------------------------------------------------------------
# Voix (ElevenLabs) : une réplique à la fois, mise en cache dans scenes/audio/
# ---------------------------------------------------------------------------
AUDIO = os.path.join(ICI, "scenes", "audio")
_VERROUS_AUDIO = {}


def _scene(scene_id):
    if not scene_id.isalnum():
        raise ValueError("Identifiant de scène invalide.")
    for s in journal.lire():
        if s.get("scene_id") == scene_id:
            return s
    raise ValueError("Scène introuvable dans le journal.")


def _repliques(s):
    return [(d[0], d[1]) if isinstance(d, (list, tuple)) else (d["locuteur"], d["texte"]) for d in s["dialogue"]]


def chemin_audio(scene_id, k):
    return os.path.join(AUDIO, scene_id, f"{int(k):03d}.mp3")


def audio_replique(scene_id, k):
    """Synthétise (ou reprend du cache) la réplique k d'une scène du journal."""
    s = _scene(scene_id)
    rep = _repliques(s)
    k = int(k)
    if not 0 <= k < len(rep):
        raise ValueError("Numéro de réplique invalide.")
    personas = {f"{p['prenom']} {p['nom']}": p for p in (ad.agent(DF, i) for i in s["ids"])}
    sortie = chemin_audio(scene_id, k)
    verrou = _VERROUS_AUDIO.setdefault(sortie, threading.Lock())   # pas deux synthèses de la même réplique
    with verrou:
        try:
            voix.synthetiser_replique(rep[k][0], rep[k][1], personas, sortie)
        except voix.ErreurVoix as e:
            raise ValueError(str(e)) from None
    return {"url": f"/audio/{scene_id}/{k}.mp3", "locuteur": rep[k][0], "total": len(rep)}


def audio_scene(scene_id):
    """MP3 de toute la scène, assemblé à partir des répliques déjà synthétisées."""
    s = _scene(scene_id)
    n = len(_repliques(s))
    chemins = [chemin_audio(scene_id, k) for k in range(n)]
    if not all(os.path.exists(c) for c in chemins):
        raise ValueError("Écoutez d'abord toute la scène : l'audio complet est assemblé à partir des répliques.")
    return b"".join(open(c, "rb").read() for c in chemins)


def audios_prets(scene_id):
    d = os.path.join(AUDIO, scene_id)
    return sorted(int(f[:3]) for f in os.listdir(d) if f.endswith(".mp3")) if os.path.isdir(d) else []


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
CONNEXION_COUPEE = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)


class Serveur(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """N'affiche pas de trace quand le navigateur coupe une connexion : c'est normal."""
        if isinstance(sys.exc_info()[1], CONNEXION_COUPEE):
            return
        super().handle_error(request, client_address)


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
        except CONNEXION_COUPEE:                     # le navigateur a fermé la requête (page rechargée,
            pass                                     # onglet fermé, rafraîchissement automatique) : sans gravité
        except ValueError as e:                      # configuration ou demande invalide
            self._envoyer_erreur(str(e), 400)
        except Exception as e:                       # noqa: BLE001
            self._envoyer_erreur(f"{type(e).__name__} : {e}", 500)

    def _envoyer_erreur(self, message, code):
        try:
            self._json({"erreur": message}, code)
        except CONNEXION_COUPEE:
            pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        self._erreurs(lambda: self._get(u, q))

    def _mp3(self, data, nom=None):
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(data)))
        if nom:
            self.send_header("Content-Disposition", f'attachment; filename="{nom}"')
        self.end_headers()
        self.wfile.write(data)

    def _get(self, u, q):
        if u.path.startswith("/audio/"):
            morceaux = u.path.split("/")                       # /audio/<scene>/<k>.mp3 ou scene.mp3
            if len(morceaux) != 4 or not morceaux[2].isalnum():
                raise ValueError("Chemin audio invalide.")
            if morceaux[3] == "scene.mp3":
                return self._mp3(audio_scene(morceaux[2]), f"scene_{morceaux[2]}.mp3")
            k = morceaux[3].removesuffix(".mp3")
            if not k.isdigit() or not os.path.exists(chemin_audio(morceaux[2], k)):
                return self._json({"erreur": "audio introuvable"}, 404)
            with open(chemin_audio(morceaux[2], k), "rb") as f:
                return self._mp3(f.read())
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
                        "colonnes": ad.colonnes_info(DF), "travaux": travaux_actifs(), "voix": voix.etat()})
        elif u.path == "/api/voix":
            self._json(voix.etat())
        elif u.path.startswith("/api/audio/"):
            self._json({"pretes": audios_prets(u.path.rsplit("/", 1)[1])})
        elif u.path.startswith("/api/job/"):
            job = JOBS.get(u.path.rsplit("/", 1)[1])
            self._json(etat_job(job) if job else {"etat": "inconnu"}, 200 if job else 404)
        elif u.path == "/api/scenes":
            jugees = juge.lire()
            scenes = journal.lire()[::-1]
            for sc in scenes:                      # évaluation la plus récente du juge, faite pendant ou après
                ev = jugees.get(sc["scene_id"])
                if ev:
                    sc["juge"], sc["valide"] = ev, ev.get("valide", sc.get("valide"))
            self._json(scenes)
        elif u.path == "/api/stats":
            self._json(statistiques(q))
        elif u.path == "/api/modele":
            self._json(etat_modele((q.get("backend") or ["test"])[0], (q.get("modele") or [None])[0],
                                   (q.get("base_url") or [None])[0]))
        elif u.path == "/api/analyses":
            self._json(analyses())
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
                                                          exiger_zone=bool(corps.get("exiger_zone")),
                                                          taille=int(corps.get("taille", 2)))]
            self._json({"ids": ids})
        elif u.path == "/api/zone":
            cfg = ad.normaliser_config(corps.get("config"))
            agents = [ad.agent(DF, i) for i in corps.get("ids", [])]
            self._json({"zone": ad.zone(agents, cfg) if len(agents) == 2 else None})
        elif u.path == "/api/lancer":
            self._json(lancer(corps))
        elif u.path.startswith("/api/audio/"):
            morceaux = u.path.split("/")                       # /api/audio/<scene>/<k>
            if len(morceaux) != 5:
                raise ValueError("Chemin audio invalide.")
            self._json(audio_replique(morceaux[3], morceaux[4]))
        elif u.path.startswith("/api/juger/"):
            self._json(propre(juger_apres_coup(u.path.rsplit("/", 1)[1], corps)))
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
    serveur = Serveur(("127.0.0.1", port), Gestionnaire)
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