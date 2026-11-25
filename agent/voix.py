"""
Synthèse vocale des scènes avec ElevenLabs (optionnel)
======================================================

Chaque persona reçoit une voix selon son sexe et son âge (moins de 55 ans :
« jeune », sinon « age »). Les identifiants de voix se choisissent dans la
bibliothèque ElevenLabs et se mettent dans voix.json :

    {
      "homme_jeune": "<voice_id>",  "homme_age": "<voice_id>",
      "femme_jeune": "<voice_id>",  "femme_age": "<voice_id>",
      "narrateur":   "<voice_id>"          # optionnel : la voix du syndic
    }

Deux façons d'accéder à ElevenLabs
----------------------------------

1. EN DIRECT, avec sa propre clé. Elle est cherchée dans la variable
   d'environnement ELEVENLABS_API_KEY, puis dans le fichier cle_elevenlabs.txt
   placé à côté de ce fichier. Ce fichier est exclu de Git : la clé reste sur
   votre ordinateur. Ne l'écrivez jamais dans un fichier .py : le dépôt est
   public, et une clé publiée est volée en quelques minutes.

2. PAR LE RELAIS du groupe (dossier voix-relais/). La clé vit alors chez
   Cloudflare et personne n'a besoin de l'avoir : il suffit du fichier
   relais.json, à côté de ce fichier, qui contient l'adresse et le jeton :

       {"url": "https://voix-labo.xxx.workers.dev", "jeton": "..."}

   Le relais limite la longueur des répliques et le nombre de caractères par
   jour ; le jeton se change en une commande si besoin.

Le relais est utilisé dès que relais.json existe. Sinon, on passe en direct.

Utilisation :
  - en ligne de commande : generer_audio(dialogue, personas_par_nom, sortie)
    produit un MP3 de toute la scène ;
  - dans le labo : synthetiser_replique(...) produit une réplique à la fois,
    ce qui permet d'écouter la scène pendant que la suite se prépare.
"""

import json
import os
import re
import urllib.error
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
CHEMIN_VOIX = os.path.join(ICI, "voix.json")
FICHIER_CLE = os.path.join(ICI, "cle_elevenlabs.txt")
FICHIER_RELAIS = os.path.join(ICI, "relais.json")
DIRECT = os.environ.get("ELEVENLABS_URL", "https://api.elevenlabs.io")
MODELE = "eleven_multilingual_v2"
# Sans User-Agent, Python s'annonce « Python-urllib/3.x », que Cloudflare bloque
# d'office : la requête n'atteint jamais le relais.
UA = "labo-agents-ter/1.0 (projet universitaire)"
CATEGORIES = ("homme_jeune", "homme_age", "femme_jeune", "femme_age")


class ErreurVoix(Exception):
    """Erreur de synthèse vocale, avec un message lisible."""


def interception(page, reponse, r):
    """Décrit une réponse qui ne vient pas du relais : qui a bloqué, et quoi faire."""
    def cherche(motif):
        m = re.search(motif, page, re.I | re.S)
        return " ".join(m.group(1).split())[:120] if m else None

    titre = cherche(r"<title[^>]*>(.*?)</title>")
    code = cherche(r"Error\s*(\d{3,4})")
    ray = reponse.headers.get("cf-ray") or cherche(r"Ray ID:?\s*(?:<[^>]*>\s*)*([0-9a-f]{12,})")
    serveur = reponse.headers.get("Server")
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

    lignes = [f"La requête vers le relais ({r['url']}) n'est jamais arrivée : "
              f"un intermédiaire a répondu à sa place (code {reponse.code})."]
    details = [("page", titre), ("code d'erreur", code), ("référence", ray), ("serveur", serveur)]
    connus = [f"{nom} : {v}" for nom, v in details if v]
    if connus:
        lignes.append("Ce que dit cette réponse — " + " ; ".join(connus) + ".")
    if proxy:
        lignes.append(f"Un proxy est configuré pour Python (HTTPS_PROXY = {proxy}) : c'est "
                      "probablement lui qui filtre.")
    lignes.append("À essayer, dans l'ordre : connecter l'ordinateur au partage de connexion du "
                  "téléphone et relancer une écoute ; sinon désactiver l'analyse HTTPS de "
                  "l'antivirus ; sinon demander l'ouverture de *.workers.dev sur le réseau.")
    return "\n".join(lignes)


def relais():
    """L'accès par le relais du groupe : {"url", "jeton"}, ou None s'il n'est pas configuré."""
    if not os.path.exists(FICHIER_RELAIS):
        return None
    try:
        with open(FICHIER_RELAIS, encoding="utf-8-sig") as f:
            r = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ErreurVoix(f"relais.json illisible : {e}") from None
    url, jeton = str(r.get("url", "")).strip().rstrip("/"), str(r.get("jeton", "")).strip()
    if not url or not jeton:
        raise ErreurVoix('relais.json doit contenir "url" et "jeton".')
    return {"url": url, "jeton": jeton}


def cle():
    """La clé ElevenLabs : variable d'environnement, sinon fichier cle_elevenlabs.txt."""
    c = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not c and os.path.exists(FICHIER_CLE):
        with open(FICHIER_CLE, encoding="utf-8-sig") as f:
            c = f.read().strip().strip('"').strip("'")
    return c


def charger_voix():
    if not os.path.exists(CHEMIN_VOIX):
        raise ErreurVoix("voix.json manquant dans le dossier agent/ : voir l'en-tête de voix.py.")
    try:
        with open(CHEMIN_VOIX, encoding="utf-8") as f:
            voix = json.load(f)
    except json.JSONDecodeError as e:
        raise ErreurVoix(f"voix.json illisible : {e}") from None
    manquantes = [c for c in CATEGORIES if not voix.get(c)]
    if manquantes:
        raise ErreurVoix(f"voix.json ne donne pas de voix pour : {', '.join(manquantes)}.")
    return voix


def etat():
    """La voix est-elle utilisable ? (pour l'indicateur du labo, sans appeler l'API)"""
    try:
        r = relais()
    except ErreurVoix as e:
        return {"ok": False, "message": str(e)}
    if r:
        try:
            charger_voix()
        except ErreurVoix as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "message": f"Relais du groupe ({r['url'].split('//')[-1]}) : aucune clé nécessaire."}
    if not cle():
        return {"ok": False, "message": "Clé absente : créez agent/cle_elevenlabs.txt contenant "
                                        "seulement la clé (sk_...), puis relancez le serveur."}
    if not cle().startswith("sk_"):
        return {"ok": False, "message": "Ce n'est pas une clé : c'est sans doute l'identifiant affiché dans la liste "
                                        "des clés. Une vraie clé commence par sk_ (créez-en une nouvelle)."}
    try:
        charger_voix()
    except ErreurVoix as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "message": "Clé et voix.json trouvés."}


def categorie(p):
    sexe = "femme" if p["sexe_fiche"] == "femme" else "homme"
    return f"{sexe}_{'age' if p['age_annees'] >= 55 else 'jeune'}"


def voix_pour(nom, personas_par_nom, voix):
    """Identifiant de voix d'un locuteur. Personnage hors population (le syndic) :
    voix « narrateur » si elle existe, sinon une voix d'homme âgé."""
    if nom in personas_par_nom:
        return voix[categorie(personas_par_nom[nom])]
    return voix.get("narrateur") or voix["homme_age"]


def synthetiser(texte, voice_id, cle_api=None):
    """MP3 (octets) d'un texte, par le relais du groupe ou en direct.
    Lève ErreurVoix avec un message clair."""
    r = relais()
    if r:
        url = f"{r['url']}/v1/text-to-speech/{voice_id}"
        entetes = {"x-labo-jeton": r["jeton"], "Content-Type": "application/json",
                   "Accept": "audio/mpeg", "User-Agent": UA}
    else:
        cle_api = cle_api or cle()
        if not cle_api:
            raise ErreurVoix("Clé ElevenLabs absente : créez agent/cle_elevenlabs.txt contenant seulement "
                             "la clé, ou agent/relais.json pour passer par le relais du groupe.")
        url = f"{DIRECT}/v1/text-to-speech/{voice_id}"
        entetes = {"xi-api-key": cle_api, "Content-Type": "application/json",
                   "Accept": "audio/mpeg", "User-Agent": UA}
    corps = json.dumps({"text": texte, "model_id": MODELE}).encode("utf-8")
    req = urllib.request.Request(url, data=corps, headers=entetes)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        brut = e.read().decode("utf-8", "replace")
        try:
            charge = json.loads(brut)
        except ValueError:
            charge = {}
        if r and isinstance(charge, dict) and charge.get("erreur"):
            # Message venant du relais lui-même (jeton, plafond, longueur).
            raise ErreurVoix(f"Relais du groupe : {charge['erreur']}") from None
        detail = charge.get("detail", {}) if isinstance(charge, dict) else {}
        statut = detail.get("status", "") if isinstance(detail, dict) else ""
        message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        # Certaines réponses ne suivent pas la forme habituelle : on garde le texte brut,
        # sinon l'erreur se résume à « Forbidden » et n'apprend rien.
        if not message:
            message = " ".join(brut.split())[:300]
        if r and not e.headers.get("X-Relais-Version"):
            # Pas de signature du relais : la réponse vient d'ailleurs. On lit la page
            # de blocage, qui indique en général qui bloque et pourquoi.
            raise ErreurVoix(interception(brut, e, r)) from None
        par_ou = f" (via le relais, version {e.headers.get('X-Relais-Version')})" if r else ""
        if e.code == 402 and "paid_plan" in statut:
            raise ErreurVoix(f"ElevenLabs refuse la voix {voice_id} : avec le forfait gratuit, seules les voix "
                             "par défaut sont utilisables par l'API. Remplacez cet identifiant dans voix.json.") from None
        if e.code == 400 and "key" in message.lower():
            raise ErreurVoix("ElevenLabs refuse la clé : c'est l'identifiant de la clé, pas la clé elle-même. "
                             "Créez une nouvelle clé (elle commence par sk_) et collez-la dans "
                             "agent/cle_elevenlabs.txt.") from None
        if e.code == 401:
            raise ErreurVoix(f"Clé ElevenLabs refusée{par_ou} : {message or 'clé invalide ou supprimée'}.") from None
        if e.code == 403:
            raise ErreurVoix(
                f"ElevenLabs refuse l'accès (403){par_ou} : {message or 'aucun détail'}.\n"
                "Causes habituelles : la clé n'a pas la permission « Text to Speech », "
                "elle a été supprimée, ou l'offre ne couvre pas cette voix. "
                "Vérifiez la clé sur elevenlabs.io (Developers > API Keys).") from None
        if e.code in (402, 429):
            raise ErreurVoix(f"ElevenLabs : {message or 'crédits ou limite de la clé épuisés'}.") from None
        if e.code == 404:
            raise ErreurVoix(f"Voix {voice_id} introuvable chez ElevenLabs : vérifiez voix.json.") from None
        raise ErreurVoix(f"Erreur ElevenLabs {e.code}{par_ou} : {message or e.reason}") from None
    except urllib.error.URLError as e:
        ou = f"au relais du groupe ({r['url']})" if r else "à ElevenLabs"
        raise ErreurVoix(f"Connexion {ou} impossible : {e.reason}") from None


def synthetiser_replique(nom, texte, personas_par_nom, sortie):
    """Écrit le MP3 d'une réplique dans `sortie` (sauf s'il existe déjà) et renvoie son chemin."""
    if os.path.exists(sortie) and os.path.getsize(sortie) > 0:
        return sortie
    voix = charger_voix()
    audio = synthetiser(texte, voix_pour(nom, personas_par_nom, voix))
    os.makedirs(os.path.dirname(sortie), exist_ok=True)
    temporaire = sortie + ".part"
    with open(temporaire, "wb") as f:
        f.write(audio)
    os.replace(temporaire, sortie)
    return sortie


def generer_audio(dialogue, personas_par_nom, sortie):
    """MP3 de toute la scène (ligne de commande). dialogue = [(nom, texte), ...]."""
    try:
        voix = charger_voix()
        morceaux = [synthetiser(texte, voix_pour(nom, personas_par_nom, voix)) for nom, texte in dialogue]
    except ErreurVoix as e:
        raise SystemExit(str(e)) from None
    with open(sortie, "wb") as f:
        f.write(b"".join(morceaux))
    return sortie