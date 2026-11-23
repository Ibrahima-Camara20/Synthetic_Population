"""
Synthèse vocale de la scène avec ElevenLabs (optionnel)
=======================================================

Chaque persona reçoit une voix selon son sexe et son âge. Les identifiants de
voix se choisissent dans la bibliothèque ElevenLabs (onglet « Voices ») et se
mettent dans voix.json, par exemple :

    {
      "homme_jeune":  "<voice_id>",  "homme_age":  "<voice_id>",
      "femme_jeune":  "<voice_id>",  "femme_age":  "<voice_id>"
    }

La clé d'API se met dans la variable d'environnement ELEVENLABS_API_KEY.
Chaque réplique est synthétisée séparément (modèle multilingue), puis les
fichiers MP3 sont mis bout à bout.
"""

import json
import os
import urllib.error
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
MODELE = "eleven_multilingual_v2"


def categorie(p):
    sexe = "femme" if p["sexe_fiche"] == "femme" else "homme"
    return f"{sexe}_{'age' if p['age_annees'] >= 55 else 'jeune'}"


def synthetiser(texte, voice_id, cle):
    corps = json.dumps({"text": texte, "model_id": MODELE}).encode("utf-8")
    req = urllib.request.Request(URL.format(voice_id=voice_id), data=corps, headers={
        "xi-api-key": cle, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", {})
        except Exception:
            detail = {}
        statut = detail.get("status", "") if isinstance(detail, dict) else ""
        message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        if e.code == 402 and "paid_plan" in statut:
            raise SystemExit(
                f"ElevenLabs refuse la voix {voice_id} : {message}\n"
                "Avec le forfait gratuit, l'API n'accepte que les voix PAR DÉFAUT d'ElevenLabs "
                "(celles déjà présentes dans « Mes voix » à la création du compte), pas celles "
                "ajoutées depuis la bibliothèque. Remplacez cet identifiant dans voix.json.")
        if e.code == 401:
            raise SystemExit(f"Clé ElevenLabs refusée (401) : {message or 'clé invalide'}. "
                             "Vérifiez qu'elle n'a pas été supprimée et qu'elle a accès à Text to Speech.")
        if e.code in (402, 429):
            raise SystemExit(f"ElevenLabs ({e.code}) : {message or 'crédits ou limite de la clé épuisés'}.")
        raise SystemExit(f"Erreur ElevenLabs {e.code} pour la voix {voice_id} : {message or e.reason}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Connexion à ElevenLabs impossible : {e.reason}")


def generer_audio(dialogue, personas_par_nom, sortie):
    cle = os.environ.get("ELEVENLABS_API_KEY")
    if not cle:
        raise SystemExit("ELEVENLABS_API_KEY manquante.")
    chemin_voix = os.path.join(ICI, "voix.json")
    if not os.path.exists(chemin_voix):
        raise SystemExit("voix.json manquant : voir l'en-tête de voix.py.")
    with open(chemin_voix, encoding="utf-8") as f:
        voix = json.load(f)
    morceaux = []
    for nom, texte in dialogue:
        # Personnage hors population (le syndic) : voix « narrateur » si elle existe
        cat = categorie(personas_par_nom[nom]) if nom in personas_par_nom else \
            ("narrateur" if "narrateur" in voix else "homme_age")
        if cat not in voix:
            raise SystemExit(f"Pas de voix pour la catégorie « {cat} » dans voix.json.")
        morceaux.append(synthetiser(texte, voix[cat], cle))
    with open(sortie, "wb") as f:
        f.write(b"".join(morceaux))
    return sortie