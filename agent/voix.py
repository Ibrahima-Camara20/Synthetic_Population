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
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


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
        cat = categorie(personas_par_nom[nom])
        if cat not in voix:
            raise SystemExit(f"Pas de voix pour la catégorie « {cat} » dans voix.json.")
        morceaux.append(synthetiser(texte, voix[cat], cle))
    with open(sortie, "wb") as f:
        f.write(b"".join(morceaux))
    return sortie
