"""
Population synthétique - Partie 2 : scène automatique entre deux agents
=======================================================================

1. On part de la population d'agents (population_agents.csv, produite par
   personas.py) : profil sociodémographique exact + personnalité OCEAN tirée.
2. On applique un scénario (ici : la hausse des charges d'une copropriété).
   Les enjeux de chaque persona sont CALCULÉS à partir de sa fiche : sa part
   des travaux (quote-part x budget) et le poids de cette part dans son revenu.
   Son objectif dans la scène en découle (partie « symbolique »).
3. On choisit automatiquement deux copropriétaires aux intérêts opposés.
4. Deux agents dialoguent : chacun a son propre prompt et ne voit que la
   conversation, jamais la fiche de l'autre.
5. On exporte la scène (Markdown, JSON, texte pour la synthèse vocale) et,
   en option, un fichier audio avec ElevenLabs.

Exemples :
    python scene.py --backend test                       # sans modèle, pour tester
    python scene.py --backend openai --modele gpt-4o-mini
    python scene.py --backend ollama --modele qwen3.5:4b                 # Ollama en local
    python scene.py --backend anthropic --modele claude-sonnet-5-5 --tours 14
    python scene.py --backend openai --modele gpt-4o-mini --ids 12,345 --voix
"""

import argparse
import json
import os
import re
import sys
import numpy as np
import pandas as pd

from llm import ClientLLM, ErreurLLM
import personas

ICI = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Scénario
# ---------------------------------------------------------------------------
SCENARIO = {
    "titre": "La hausse des charges de la copropriété",
    "lieu": "le hall de l'immeuble, un soir, devant la convocation à l'assemblée générale "
            "affichée au mur",
    "budget_annuel": 30000,
    "projet": "rénover le hall (éclairage, carrelage, boîtes aux lettres), remplacer "
              "l'ascenseur et installer un visiophone, pour 30 000 € de plus par an",
    "urgent": "la fuite au sous-sol et la porte du local poubelles",
}


def enjeux(p, scenario=SCENARIO):
    """Ce que le projet coûte à la persona et l'objectif qui en découle."""
    part_annuelle = p["tantiemes"] / 1000 * scenario["budget_annuel"]
    mensuel = part_annuelle / 12
    effort = mensuel / p["revenu_mensuel"]
    if p["revenu"] == "modeste" or effort >= 0.06:
        position = "contre"
        objectif = ("Empêcher la hausse des charges. Tu acceptes au plus les réparations "
                    f"urgentes ({scenario['urgent']}), pas le reste.")
    elif p["revenu"] == "aise" or effort <= 0.03:
        position = "pour"
        objectif = ("Faire voter tout le projet : plus de confort, un immeuble plus haut "
                    "de gamme, et la valeur de ton appartement qui monte.")
    else:
        position = "partage"
        objectif = ("Tu hésites : tu veux bien un peu de confort, mais pas à n'importe quel prix. "
                    "Tu cherches à réduire le projet.")
    # Nuance tirée de la santé (A10) : l'ascenseur compte pour qui se déplace mal
    if p.get("sante", "bonne sante") != "bonne sante" and p["etage"] >= 2:
        objectif += (" Mais ta santé rend l'ascenseur important pour toi : sur ce point précis, "
                     "tu peux te montrer plus ouvert(e).")
    return {"part_annuelle": round(part_annuelle), "mensuel": round(mensuel),
            "effort_pct": round(100 * effort, 1), "position": position, "objectif": objectif}


def eligibles(df):
    """Copropriétaires d'un immeuble en ville, adultes."""
    return df[(df["logement"] == "proprietaire") & (df["zone"] == "ville")].copy()


def choisir_paire(df, rng, ids=None):
    """Deux copropriétaires aux intérêts opposés (un « pour », un « contre »).
    Parmi les paires possibles, on favorise un grand écart d'effort financier et
    une faible agréabilité (plus de chances de vrai désaccord), puis on tire au
    hasard parmi les meilleures pour varier les scènes."""
    if ids:
        a, b = (df[df["id"] == i].iloc[0] for i in ids)
        return a, b
    el = eligibles(df)
    ej = [enjeux(p) for _, p in el.iterrows()]
    el["position"] = [e["position"] for e in ej]
    el["effort"] = [e["effort_pct"] for e in ej]
    pour, contre = el[el["position"] == "pour"], el[el["position"] == "contre"]
    if pour.empty or contre.empty:
        raise SystemExit("Pas de paire « pour / contre » parmi les copropriétaires éligibles.")
    paires = []
    for _, a in pour.iterrows():
        for _, b in contre.iterrows():
            score = (b["effort"] - a["effort"]) - 1.5 * (a["z_agreabilite"] + b["z_agreabilite"])
            paires.append((score, a["id"], b["id"]))
    paires.sort(reverse=True)
    _, ia, ib = paires[int(rng.integers(0, min(10, len(paires))))]
    return df[df["id"] == ia].iloc[0], df[df["id"] == ib].iloc[0]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def consigne(p, autre, e, scenario=SCENARIO, commence=False):
    vouv = "Vous vous vouvoyez : vous êtes voisins, pas amis."
    return f"""Tu joues {p['prenom']} {p['nom']} dans une courte scène de théâtre réaliste.

TA FICHE (pour toi seul, ne la récite jamais)
{personas.texte_fiche(p)}

LA SITUATION
Lieu : {scenario['lieu']}.
Tu croises {autre['prenom']} {autre['nom']}, {autre['age_annees']} ans, {'une autre copropriétaire' if autre['sexe_fiche'] == 'femme' else 'un autre copropriétaire'} de l'immeuble.
Le syndic propose de {scenario['projet']}.
Pour toi, cela représente {e['part_annuelle']} € par an, soit {e['mensuel']} € par mois ({str(e['effort_pct']).replace('.', ',')} % de ton revenu).

TON OBJECTIF
{e['objectif']}

COMMENT JOUER
- Montre ta personnalité par ta façon de parler et d'argumenter, ne la décris jamais.
- Ne te présente pas, n'énumère pas tes caractéristiques, ne dis pas « en tant que… ».
- Une à trois phrases par réplique, langage oral et naturel. {vouv}
- Ne cède pas sans un vrai argument : un désaccord qui reste ouvert est normal.
- Tu peux utiliser tes chiffres, mais n'invente pas de faits importants.
- Écris uniquement ta réplique : pas de nom, pas de guillemets, pas de didascalies.
- Ne dis jamais que tu es une IA ou un personnage.
{"- C'est toi qui engages la conversation." if commence else ""}"""


def nettoyer(texte, prenoms):
    """Retire ce que le modèle ajoute parfois : nom du locuteur, didascalies, guillemets."""
    t = re.sub(r"<think>.*?(</think>|$)", "", texte, flags=re.S).strip()   # réflexion des modèles Qwen3…
    t = re.sub(r"\*[^*]*\*", " ", t)                       # *soupire*
    t = re.sub(r"\([^)]*\)", " ", t)                       # (soupire)
    noms = "|".join(re.escape(n) for n in prenoms)
    t = re.sub(rf"^\s*({noms})(\s+[A-ZÉÈ][\w'-]+)?\s*:\s*", "", t)      # « Michel Muller : »
    t = t.strip().strip('"«»“”\'').strip()
    return re.sub(r"\s{2,}", " ", t)


# ---------------------------------------------------------------------------
# Backend de test : des répliques construites à partir des fiches
# ---------------------------------------------------------------------------
def replique_test(p, e, tour, dernier):
    if dernier:
        return ("Très bien, on en reparlera à l'assemblée générale." if e["position"] == "pour"
                else "On votera, et je viendrai avec mes voix. Bonne soirée.")
    pour = [
        "Vous avez vu la convocation ? On va enfin rénover ce hall.",
        f"Ça fait {e['mensuel']} € par mois pour moi, c'est raisonnable pour un immeuble qui prend de la valeur.",
        "Un hall vieillot, c'est des milliers d'euros en moins à la revente.",
        "L'ascenseur a trente ans, il faut penser à l'avenir de l'immeuble.",
        "On peut demander un échéancier au syndic, ça étale l'effort.",
    ]
    contre = [
        f"J'ai fait le calcul : {e['mensuel']} € de plus par mois. C'est {round(e['effort_pct'])} % de ce que je touche.",
        "Je ne vends pas, moi. Ce hall me convient très bien.",
        f"Réparer ce qui est cassé, d'accord : {SCENARIO['urgent']}. Le reste, non.",
        "Payer en plusieurs fois, ça reste payer.",
        "Venez avec vos arguments en assemblée, je viendrai avec les miens.",
    ]
    lignes = pour if e["position"] == "pour" else contre
    return lignes[(tour // 2) % len(lignes)]


# ---------------------------------------------------------------------------
# Moteur de dialogue
# ---------------------------------------------------------------------------
def jouer_scene(a, b, client, tours=12, scenario=SCENARIO, verbeux=True):
    """a commence (c'est celui qui veut le changement). Renvoie la liste des répliques."""
    ea, eb = enjeux(a, scenario), enjeux(b, scenario)
    agents = [(a, b, ea, consigne(a, b, ea, scenario, commence=True)),
              (b, a, eb, consigne(b, a, eb, scenario))]
    dialogue = []
    for tour in range(tours):
        p, autre, e, systeme = agents[tour % 2]
        dernier = tour >= tours - 2
        if client.backend == "test":
            texte = replique_test(p, e, tour, dernier)
        else:
            # Vue de l'agent : ses répliques = assistant, celles de l'autre = user
            messages = [{"role": "user", "content": "[La scène commence.]"}] if tour % 2 == 0 else []
            for i, (nom, rep) in enumerate(dialogue):
                role = "assistant" if (i % 2) == (tour % 2) else "user"
                messages.append({"role": role, "content": rep})
            if dernier:
                messages[-1]["content"] += ("\n\n[Indication : c'est ta dernière réplique, "
                                            "termine la conversation, d'accord ou non.]")
            texte = nettoyer(client.repondre(systeme, messages), [p['prenom'], autre['prenom']])
        nom = f"{p['prenom']} {p['nom']}"
        dialogue.append((nom, texte))
        if verbeux:
            print(f"{nom} : {texte}\n", flush=True)
    return dialogue, ea, eb


def verifier(dialogue, a, b):
    """Contrôles simples des défauts vus dans les essais précédents."""
    txt = " ".join(r for _, r in dialogue)
    return {
        "repliques": len(dialogue),
        "codes_attributs": len(re.findall(r"\bA\d{1,2}\b", txt)),
        "en_tant_que": len(re.findall(r"[Ee]n tant que", txt)),
        "mentions_ia": len(re.findall(r"\b(IA|intelligence artificielle|modèle de langage)\b", txt)),
        "longueur_moyenne_mots": round(float(np.mean([len(r.split()) for _, r in dialogue])), 1),
    }


def exporter(a, b, ea, eb, dialogue, controles, client, dossier):
    os.makedirs(dossier, exist_ok=True)
    base = os.path.join(dossier, f"scene_{a['id']}_{b['id']}")
    md = [f"# {SCENARIO['titre']}", "",
          f"*Lieu : {SCENARIO['lieu']}.*", "",
          f"*Projet : {SCENARIO['projet']}.*", "",
          f"*Modèle : {client.backend} {client.modele or ''}*", "", "## Les personas", ""]
    for p, e in ((a, ea), (b, eb)):
        md += [f"### {p['prenom']} {p['nom']} (individu {p['id']} de la population)", "",
               "```", personas.texte_fiche(p), "```", "",
               f"- Part des travaux : {e['part_annuelle']} € par an, {e['mensuel']} € par mois "
               f"({str(e['effort_pct']).replace('.', ',')} % du revenu)",
               f"- Position : **{e['position']}**", ""]
    md += ["## La scène", ""] + [f"**{n} :** {r}\n" for n, r in dialogue]
    md += ["## Contrôles", "", *[f"- {k} : {v}" for k, v in controles.items()]]
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    with open(base + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(f"{n}: {r}" for n, r in dialogue))
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump({"scenario": SCENARIO,
                   "personas": [{**{k: (v.item() if hasattr(v, "item") else v) for k, v in p.items()},
                                 "enjeux": e} for p, e in ((a, ea), (b, eb))],
                   "dialogue": [{"locuteur": n, "texte": r} for n, r in dialogue],
                   "controles": controles}, f, ensure_ascii=False, indent=2)
    return base


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="test", choices=["test", "ollama", "openai", "anthropic"])
    ap.add_argument("--modele")
    ap.add_argument("--base-url")
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--max-tokens", type=int, default=400,
                    help="longueur maximale d'une réponse (augmenter pour les modèles qui réfléchissent)")
    ap.add_argument("--sans-reflexion", action="store_true",
                    help="demande aux modèles qui réfléchissent (Qwen3…) de répondre directement : plus rapide")
    ap.add_argument("--tours", type=int, default=12, help="nombre total de répliques")
    ap.add_argument("--graine", type=int, default=0, help="change la paire choisie")
    ap.add_argument("--ids", help="forcer deux individus, ex. 12,345 (le premier commence)")
    ap.add_argument("--population", default=os.path.join(ICI, "population_agents.csv"))
    ap.add_argument("--sortie", default=os.path.join(ICI, "scenes"))
    ap.add_argument("--voix", action="store_true", help="générer l'audio avec ElevenLabs")
    args = ap.parse_args()

    # Les personas doivent décrire la population_finale.csv ACTUELLE de l'algorithme
    if os.path.exists(personas.POPULATION_FINALE):
        if not personas.est_a_jour(args.population):
            print("population_agents.csv absent ou ne correspond plus à population_finale.csv "
                  "(main.py relancé ?) : régénération des personas.\n")
            personas.generer_fichiers(afficher=False)
    elif not os.path.exists(args.population):
        sys.exit(f"population_finale.csv introuvable ({personas.POPULATION_FINALE}) : lancez main.py.")
    df = pd.read_csv(args.population)
    brut = (np.loadtxt(personas.POPULATION_FINALE, delimiter=",", skiprows=1, dtype=int)
            if os.path.exists(personas.POPULATION_FINALE) else None)

    try:
        client = ClientLLM(args.backend, args.modele, args.base_url, args.temperature,
                           args.max_tokens, args.sans_reflexion)
    except ErreurLLM as e:
        sys.exit(f"Erreur : {e}")

    rng = np.random.default_rng(args.graine)
    ids = [int(x) for x in args.ids.split(",")] if args.ids else None
    a, b = choisir_paire(df, rng, ids)

    print(f"=== {SCENARIO['titre']} ===\n")
    for p in (a, b):
        e = enjeux(p)
        if brut is not None:
            ligne = ",".join(str(v) for v in brut[p["id"] - 1])
            print(f"[Individu {p['id']} de population_finale.csv, ligne {p['id'] + 1} dans Excel : {ligne}]")
        print(personas.texte_fiche(p))
        print(f"Enjeu : {e['mensuel']} € par mois ({str(e['effort_pct']).replace('.', ',')} % du revenu), "
              f"position : {e['position']}\n")
    print("--- Scène ---\n")
    try:
        dialogue, ea, eb = jouer_scene(a, b, client, args.tours)
    except ErreurLLM as e:
        sys.exit(f"Erreur du modèle : {e}")

    controles = verifier(dialogue, a, b)
    base = exporter(a, b, ea, eb, dialogue, controles, client, args.sortie)
    print("Contrôles :", controles)
    print(f"Scène enregistrée : {base}.md / .txt / .json")

    if args.voix:
        import voix
        chemin = voix.generer_audio(dialogue, {f"{p['prenom']} {p['nom']}": p for p in (a, b)},
                                    base + ".mp3")
        print(f"Audio : {chemin}")


if __name__ == "__main__":
    main()