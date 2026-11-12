"""
Population synthétique - Partie 2 : des individus aux personas
==============================================================

1. Décoder chaque individu de la population (A0..A11) grâce à attributs.json.
2. Tirer un profil de personnalité OCEAN pour chacun (tirage encadré, cours
   diapositives 22 à 26) : la personnalité n'est pas optimisée avec le
   solveur, elle est tirée après coup, avec un lien faible avec l'âge et le
   sexe et une forte diversité à l'intérieur de chaque groupe.
3. Construire une fiche de persona au format du professeur : nom, âge,
   situation, revenu, logement, traits décrits par des comportements.

Usage :
    python personas.py [population_finale.csv]   -> population_agents.csv
"""

import json
import os
import sys
import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
TRAITS = ["ouverture", "conscienciosite", "extraversion", "agreabilite", "nevrosisme"]

# ---------------------------------------------------------------------------
# Personnalité : paramètres du tirage (HYPOTHÈSES, ordres de grandeur)
# ---------------------------------------------------------------------------
# Corrélations entre traits (scores standardisés), valeurs modérées proches de
# celles rapportées dans la littérature sur le Big Five. À remplacer par les
# corrélations d'une vraie enquête par panel si on en dispose.
CORRELATIONS = np.array([
    #  O      C      E      A      N
    [1.00,  0.10,  0.25,  0.10, -0.10],   # O
    [0.10,  1.00,  0.15,  0.25, -0.30],   # C
    [0.25,  0.15,  1.00,  0.15, -0.25],   # E
    [0.10,  0.25,  0.15,  1.00, -0.25],   # A
    [-0.10, -0.30, -0.25, -0.25, 1.00],   # N
])

# Décalages de moyenne, en écarts-types. Ils sont volontairement petits : le
# cours insiste sur le lien FAIBLE entre sociodémographie et personnalité.
DECALAGE_AGE = {
    "18-29": np.array([+0.10, -0.20, +0.05, -0.10, +0.10]),
    "30-59": np.array([0.00, 0.00, 0.00, 0.00, 0.00]),
    "60+":   np.array([-0.15, +0.25, -0.05, +0.25, -0.20]),
}
DECALAGE_SEXE = {
    "homme":       np.array([0.00, -0.05, -0.05, -0.15, -0.15]),
    "femme":       np.array([0.00, +0.05, +0.05, +0.15, +0.15]),
    "non precise": np.zeros(5),
}

# Traduction en comportements, pour un niveau nettement haut ou bas.
COMPORTEMENTS = {
    "ouverture": {
        "haut": "curieux des idées nouvelles, aime imaginer d'autres façons de faire",
        "bas": "tient à ses habitudes, se méfie des nouveautés et des « embellissements »",
    },
    "conscienciosite": {
        "haut": "a le souci du détail, connaît les règles et les chiffres par cœur",
        "bas": "peu soucieux des détails, décide à l'instinct et improvise",
    },
    "extraversion": {
        "haut": "parle beaucoup et avec aplomb, aime convaincre",
        "bas": "réservé, parle peu mais va droit au but",
    },
    "agreabilite": {
        "haut": "cherche le compromis, évite de froisser",
        "bas": "tient tête, parle sans ménagement, peut se montrer condescendant",
    },
    "nevrosisme": {
        "haut": "s'inquiète vite, prend les choses à cœur, s'agace facilement",
        "bas": "garde son calme, difficile à déstabiliser",
    },
}
SEUIL = 0.6          # |z| au-delà duquel un trait est considéré comme marqué

# ---------------------------------------------------------------------------
# Éléments de fiche (noms, métiers, montants) : HYPOTHÈSES de mise en scène
# ---------------------------------------------------------------------------
PRENOMS = {
    ("homme", "18-29"): ["Hugo", "Lucas", "Théo", "Nathan", "Enzo", "Yanis", "Maxime"],
    ("homme", "30-59"): ["Julien", "Nicolas", "Sébastien", "Karim", "Thomas", "Laurent", "Romain"],
    ("homme", "60+"):   ["Michel", "Gérard", "Bernard", "Alain", "Jean-Pierre", "Daniel", "André"],
    ("femme", "18-29"): ["Léa", "Manon", "Chloé", "Inès", "Camille", "Sarah", "Emma"],
    ("femme", "30-59"): ["Aurélie", "Sandrine", "Nadia", "Céline", "Julie", "Sophie", "Fatima"],
    ("femme", "60+"):   ["Josiane", "Monique", "Françoise", "Nicole", "Christiane", "Odette", "Martine"],
}
NOMS = ["Martin", "Bernard", "Dubois", "Durand", "Lefebvre", "Moreau", "Garcia", "Roux",
        "Fournier", "Girard", "Bonnet", "Lambert", "Fontaine", "Rousseau", "Mercier",
        "Blanc", "Guerin", "Muller", "Henry", "Ferrand", "Delmas", "Benali", "Nguyen", "Perrin"]
METIERS = {
    "modeste": ["agent d'entretien", "aide-soignant(e)", "caissier(e)", "manutentionnaire",
                "secrétaire médicale", "vendeur(se)"],
    "moyen":   ["infirmier(e)", "technicien(ne) de maintenance", "comptable", "professeur(e) des écoles",
                "conducteur(trice) de bus", "assistant(e) de gestion"],
    "aise":    ["consultant(e) en fusions-acquisitions", "ingénieur(e) informatique", "médecin",
                "directeur(trice) commercial(e)", "avocat(e)", "cadre bancaire"],
}
METIERS_INDEP = {
    "modeste": ["artisan(e) peintre", "auto-entrepreneur(se) livreur(se)", "coiffeur(se) à domicile"],
    "moyen":   ["commerçant(e)", "électricien(ne) à son compte", "photographe"],
    "aise":    ["architecte", "pharmacien(ne)", "chef(fe) d'entreprise"],
}
NOMS_UE = ["Silva", "Rossi", "Fernandes", "Kowalski", "Schmidt", "Popescu", "Ferreira", "Esposito"]
NOMS_HORS_UE = ["Haddad", "Diallo", "Nguyen", "Traoré", "Yilmaz", "Chen", "Mansouri", "Okafor"]

# Particularités tirées des attributs A0, A2, A6, A8, A10 (seulement les valeurs minoritaires)
PARTICULARITES = {
    "nationalite": {"etrangere hors UE": "de nationalité étrangère (hors Union européenne)",
                    "etrangere UE": "de nationalité étrangère (Union européenne)"},
    "tabac": {"fumeur": "fume", "vapoteur": "vapote"},
    "engagement": {"militant associatif ou politique": "militant(e) dans une association ou un parti",
                   "syndique": "syndiqué(e)"},
    "residence_secondaire": {"oui": "possède une résidence secondaire"},
    "sante": {"probleme de sante limitant": "un problème de santé limite ses déplacements",
              "handicap lourd": "vit avec un handicap lourd"},
}

REVENU_MENSUEL = {"modeste": (900, 1500), "moyen": (1600, 3200), "aise": (3500, 8000)}
TAILLE_LOGEMENT = {"seul": [1, 2, 2, 3], "en couple": [2, 3, 3, 4], "famille monoparentale": [3, 3, 4]}
ANNEE_COURANTE = 2026


def accorder(texte, sexe):
    """'infirmier(e)' -> 'infirmier' ou 'infirmiere' selon le sexe."""
    import re
    def rep(m):
        base, fem = m.group(1), m.group(2)
        if sexe != "femme":
            return base
        # remplacements usuels : -eur(se), -er(e), -ien(ne), -teur(trice)
        if fem == "trice":
            return base[:-4] + "trice" if base.endswith("teur") else base + "trice"
        if fem == "e" and base.endswith("ier"):
            return base[:-3] + "ière"
        if fem == "se" and base.endswith("eur"):
            return base[:-1] + "se"
        if fem == "fe" and base.endswith("f"):
            return base + "fe"
        return base + fem
    return re.sub(r"(\w+)\((\w+)\)", rep, texte)


# ---------------------------------------------------------------------------
def charger_correspondance():
    with open(os.path.join(ICI, "attributs.json"), encoding="utf-8") as f:
        return json.load(f)["attributs"]


def decoder(P, corr):
    """Tableau (n, 12) d'entiers -> DataFrame d'attributs lisibles."""
    colonnes = {}
    for code, info in corr.items():
        j = int(code[1:])
        colonnes[info["nom"]] = [info["valeurs"][v] for v in P[:, j]]
    return pd.DataFrame(colonnes)


def tirer_ocean(df, rng):
    """Tirage encadré : moyenne légèrement décalée selon âge et sexe,
    corrélations entre traits, variance individuelle forte (écart-type 1)."""
    L = np.linalg.cholesky(CORRELATIONS)
    z = rng.standard_normal((len(df), 5)) @ L.T
    decal = np.array([DECALAGE_AGE[a] + DECALAGE_SEXE[s] for a, s in zip(df["age"], df["sexe"])])
    z = z + decal
    # Score sur l'échelle du BFI (1 à 5), centrée sur 3
    score = np.clip(3 + 0.7 * z, 1, 5)
    for k, t in enumerate(TRAITS):
        df[f"z_{t}"] = z[:, k].round(2)
        df[t] = score[:, k].round(2)
    return df


def traits_marques(ligne, maximum=3):
    """Les traits les plus marqués, traduits en comportements."""
    zs = [(abs(ligne[f"z_{t}"]), t, "haut" if ligne[f"z_{t}"] > 0 else "bas") for t in TRAITS]
    zs = sorted([x for x in zs if x[0] >= SEUIL], reverse=True)[:maximum]
    return [COMPORTEMENTS[t][niv] for _, t, niv in zs]


def construire_fiche(ligne, rng):
    """Ajoute les éléments concrets d'une fiche au format du professeur."""
    sexe = ligne["sexe"] if ligne["sexe"] != "non precise" else rng.choice(["homme", "femme"])
    tranche = ligne["age"]
    age_max_60 = 68 if ligne["activite"] != "inactif" else 88   # actifs de 60+ : fin de carrière
    age = {"18-29": rng.integers(20, 30), "30-59": rng.integers(30, 60),
           "60+": rng.integers(60, age_max_60)}[tranche]
    prenom = rng.choice(PRENOMS[(sexe, tranche)])
    nom = rng.choice({"francaise": NOMS, "etrangere UE": NOMS_UE,
                      "etrangere hors UE": NOMS_HORS_UE}[ligne["nationalite"]])

    rev = ligne["revenu"]
    lo, hi = REVENU_MENSUEL[rev]
    revenu = rng.uniform(lo, hi)
    if ligne["foyer"] == "en couple":          # revenus du foyer : on ajoute ceux du conjoint
        revenu *= rng.uniform(1.5, 1.9)
    revenu = int(round(revenu, -1))

    if ligne["activite"] == "salarie":
        metier = accorder(rng.choice(METIERS[rev]), sexe)
        situation = metier
    elif ligne["activite"] == "independant":
        metier = accorder(rng.choice(METIERS_INDEP[rev]), sexe)
        situation = metier
    else:
        if age >= 60:
            metier = accorder(rng.choice(METIERS[rev]), sexe)
            situation = ("retraitée" if sexe == "femme" else "retraité") + f", ancien(ne) {metier}"
            situation = accorder(situation, sexe)
        elif tranche == "18-29":              # inactif de 18 à 29 ans : étudiant
            situation = "étudiante" if sexe == "femme" else "étudiant"
        else:
            situation = "sans emploi"

    foyer = ligne["foyer"]
    if foyer == "seul":
        if age >= 65 and rng.random() < 0.5:
            foyer_txt = "veuve" if sexe == "femme" else "veuf"
        else:
            foyer_txt = "célibataire" if sexe == "femme" else "célibataire"
    elif foyer == "en couple":
        foyer_txt = "en couple"
    else:
        foyer_txt = "parent isolé avec un enfant"

    pieces = int(rng.choice(TAILLE_LOGEMENT[foyer]))
    etage = int(rng.integers(0, 7))
    anciennete = int(rng.integers(1, max(2, age - 24)))
    tantiemes = int(round(rng.normal(30 + 28 * pieces + 3 * etage, 6)))

    particularites = [accorder(PARTICULARITES[col][ligne[col]], sexe)
                      for col in PARTICULARITES if ligne[col] in PARTICULARITES[col]]

    return {
        "particularites": " ; ".join(particularites),
        "prenom": prenom, "nom": nom, "sexe_fiche": sexe, "age_annees": int(age),
        "situation": situation, "foyer_txt": foyer_txt, "revenu_mensuel": revenu,
        "pieces": pieces, "etage": etage, "annee_achat": ANNEE_COURANTE - anciennete,
        "tantiemes": tantiemes,
    }


def construire_population_agents(fichier_population, graine=0):
    rng = np.random.default_rng(graine)
    P = np.loadtxt(fichier_population, delimiter=",", skiprows=1, dtype=int)
    df = decoder(P, charger_correspondance())
    df.insert(0, "id", range(1, len(df) + 1))
    df = tirer_ocean(df, rng)
    fiches = pd.DataFrame([construire_fiche(l, rng) for _, l in df.iterrows()])
    df = pd.concat([df, fiches], axis=1)
    df["traits"] = [" ; ".join(traits_marques(l)) for _, l in df.iterrows()]
    return df


def texte_fiche(p):
    """Fiche lisible, au format des fiches du professeur."""
    etage = {0: "au rez-de-chaussée", 1: "au 1er étage"}.get(p["etage"], f"au {p['etage']}e étage")
    pieces = f"{p['pieces']} pièce" + ("s" if p["pieces"] > 1 else "")
    zone = {"ville": "en ville", "periurbain": "en périphérie", "rural": "à la campagne"}[p["zone"]]
    traits = p["traits"] if isinstance(p["traits"], str) and p["traits"] else \
        "tempérament plutôt moyen, sans trait très marqué"
    montant = f"{p['revenu_mensuel']:,}".replace(",", " ")
    if p["logement"] == "proprietaire":
        logement = f"{pieces} {etage}, propriétaire depuis {p['annee_achat']}"
    elif p["logement"] == "locataire":
        logement = f"{pieces} {etage}, locataire"
    else:
        logement = f"{pieces} {etage}, logé gratuitement"
    if p["foyer"] == "en couple":
        revenu = "revenus du foyer"
    elif "retrait" in p["situation"]:
        revenu = "pension"
    else:
        revenu = "revenu"
    return (f"Nom : {p['prenom']} {p['nom']}\n"
            f"Âge : {p['age_annees']} ans\n"
            f"Situation : {p['situation']}, {p['foyer_txt']}\n"
            f"Revenu : environ {montant} € net par mois ({revenu})\n"
            f"Logement : {logement}, {zone}\n"
            + (f"Quote-part : {p['tantiemes']} / 1000\n" if p["logement"] == "proprietaire" else "")
            + (f"Particularités : {p['particularites']}\n"
               if isinstance(p.get("particularites"), str) and p["particularites"] else "")
            + f"Traits : {traits}")


def enregistrer(df, chemin, **options):
    """Écrit un CSV ; sous Windows, un fichier ouvert dans Excel est verrouillé."""
    try:
        df.to_csv(chemin, index=False, **options)
    except PermissionError:
        sys.exit(f"Impossible d'écrire {os.path.basename(chemin)} : le fichier est sans doute "
                 "ouvert dans Excel. Fermez-le, puis relancez la commande.")


POPULATION_FINALE = os.path.join(ICI, "..", "population_finale.csv")


def generer_fichiers(src=POPULATION_FINALE, afficher=True):
    """Construit population_agents.csv (complet) et fiches_personas.csv (lisible)."""
    df = construire_population_agents(src)
    sortie = os.path.join(ICI, "population_agents.csv")
    enregistrer(df, sortie)
    lisible = pd.DataFrame({
        "id": df["id"],
        "nom": df["prenom"] + " " + df["nom"],
        "age": df["age_annees"],
        "situation": df["situation"] + ", " + df["foyer_txt"],
        "revenu_mensuel_eur": df["revenu_mensuel"],
        "logement": df["logement"].str.replace("proprietaire", "propriétaire").str.replace(
            "loge gratuitement", "logé gratuitement") + ", " + df["zone"].str.replace(
            "periurbain", "périurbain"),
        "ouverture": df["ouverture"].round(1),
        "conscienciosite": df["conscienciosite"].round(1),
        "extraversion": df["extraversion"].round(1),
        "agreabilite": df["agreabilite"].round(1),
        "nevrosisme": df["nevrosisme"].round(1),
        "particularites": df["particularites"].fillna(""),
        "traits": df["traits"].fillna("sans trait très marqué"),
    })
    sortie_lisible = os.path.join(ICI, "fiches_personas.csv")
    enregistrer(lisible, sortie_lisible, encoding="utf-8-sig")   # utf-8-sig : accents OK dans Excel
    if afficher:
        print(f"{len(df)} personas -> {sortie}  (fichier complet, utilisé par scene.py)")
        print(f"{len(df)} fiches -> {sortie_lisible}  (version courte, à lire)")
    return df


def est_a_jour(chemin_agents, src=POPULATION_FINALE):
    """Vrai si population_agents.csv décrit bien la population_finale.csv actuelle."""
    if not os.path.exists(chemin_agents):
        return False
    P = np.loadtxt(src, delimiter=",", skiprows=1, dtype=int)
    attendu = decoder(P, charger_correspondance())
    agents = pd.read_csv(chemin_agents)
    if len(agents) != len(attendu) or not set(attendu.columns) <= set(agents.columns):
        return False
    return all((agents[c].astype(str).values == attendu[c].astype(str).values).all()
               for c in attendu.columns)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else POPULATION_FINALE
    df = generer_fichiers(src)
    print("\nMoyennes OCEAN par tranche d'âge (échelle 1 à 5) :")
    print(df.groupby("age")[TRAITS].mean().round(2))
    print("\nExemple de fiche :\n")
    print(texte_fiche(df.iloc[0]))