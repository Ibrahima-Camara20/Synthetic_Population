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

La clé d'API est cherchée, dans cet ordre :
  1. dans la variable d'environnement ELEVENLABS_API_KEY ;
  2. dans le fichier cle_elevenlabs.txt, à côté de ce fichier (dossier agent/).

Le plus simple : créer une fois pour toutes agent/cle_elevenlabs.txt contenant
seulement la clé (sk_...). Ce fichier est exclu de Git (.gitignore) : la clé reste
sur votre ordinateur et n'est jamais envoyée sur GitHub. Ne l'écrivez pas dans un
fichier .py : le dépôt est public, et une clé publiée est volée en quelques minutes.

Utilisation :
  - en ligne de commande : generer_audio(dialogue, personas_par_nom, sortie)
    produit un MP3 de toute la scène ;
  - dans le labo : synthetiser_replique(...) produit une réplique à la fois,
    ce qui permet d'écouter la scène pendant que la suite se prépare.
"""

import json
import os
import urllib.error
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
CHEMIN_VOIX = os.path.join(ICI, "voix.json")
FICHIER_CLE = os.path.join(ICI, "cle_elevenlabs.txt")
URL = os.environ.get("ELEVENLABS_URL", "https://api.elevenlabs.io") + "/v1/text-to-speech/{voice_id}"
MODELE = "eleven_multilingual_v2"
CATEGORIES = ("homme_jeune", "homme_age", "femme_jeune", "femme_age")


class ErreurVoix(Exception):
    """Erreur de synthèse vocale, avec un message lisible."""


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
    if not cle():
        return {"ok": False, "message": "Clé absente : créez agent/cle_elevenlabs.txt contenant "
                                        "seulement la clé (sk_...), puis relancez le serveur."}
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
    """MP3 (octets) d'un texte. Lève ErreurVoix avec un message clair."""
    cle_api = cle_api or cle()
    if not cle_api:
        raise ErreurVoix("Clé ElevenLabs absente : créez agent/cle_elevenlabs.txt contenant seulement la clé.")
    corps = json.dumps({"text": texte, "model_id": MODELE}).encode("utf-8")
    req = urllib.request.Request(URL.format(voice_id=voice_id), data=corps, headers={
        "xi-api-key": cle_api, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", {})
        except Exception:                                    # noqa: BLE001
            detail = {}
        statut = detail.get("status", "") if isinstance(detail, dict) else ""
        message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        if e.code == 402 and "paid_plan" in statut:
            raise ErreurVoix(f"ElevenLabs refuse la voix {voice_id} : avec le forfait gratuit, seules les voix "
                             "par défaut sont utilisables par l'API. Remplacez cet identifiant dans voix.json.") from None
        if e.code == 401:
            raise ErreurVoix(f"Clé ElevenLabs refusée : {message or 'clé invalide ou supprimée'}.") from None
        if e.code in (402, 429):
            raise ErreurVoix(f"ElevenLabs : {message or 'crédits ou limite de la clé épuisés'}.") from None
        if e.code == 404:
            raise ErreurVoix(f"Voix {voice_id} introuvable chez ElevenLabs : vérifiez voix.json.") from None
        raise ErreurVoix(f"Erreur ElevenLabs {e.code} : {message or e.reason}") from None
    except urllib.error.URLError as e:
        raise ErreurVoix(f"Connexion à ElevenLabs impossible : {e.reason}") from None


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