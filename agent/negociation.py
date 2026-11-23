"""
Population synthétique - Partie 2 : négocier jusqu'à un terrain d'entente
=========================================================================

Pour qu'un compromis soit possible, il faut :
  1. quelque chose à négocier : le projet est découpé en POSTES votables
     séparément, et le paiement peut être ÉTALÉ sur 1, 2 ou 3 ans ;
  2. une marge de manœuvre pour chaque persona, CALCULÉE depuis sa fiche :
     un plafond mensuel (part du revenu), les postes auxquels elle tient
     absolument, ceux qu'elle peut sacrifier ;
  3. vérifier qu'une ZONE D'ACCORD existe : au moins une option (postes +
     étalement) acceptable pour les deux.

Le dialogue s'arrête quand les deux agents signalent l'accord ([ACCORD]).
S'ils s'enlisent, le syndic propose un compromis tiré de la zone d'accord.
À la fin, on extrait l'accord et on VÉRIFIE qu'il respecte les limites des deux.

Tout dépend de « règles » construites par regles(scenario, marges) :
  - le coût de chaque poste est une part fixe du budget annuel du scénario
    (urgent 4/30, hall 8/30, ascenseur 15/30, visiophone 3/30) ;
  - les plafonds (en % du revenu) par position sont réglables depuis le labo.
"""

import itertools
import json
import re

import personas

# ---------------------------------------------------------------------------
# Ce qui se négocie
# ---------------------------------------------------------------------------
PARTS = {"urgent": 4, "hall": 8, "ascenseur": 15, "visiophone": 3}      # sur 30
LIBELLES = {
    "urgent": ("les réparations urgentes ({urgent})", "réparations urgentes"),
    "hall": ("la rénovation du hall (éclairage, carrelage, boîtes aux lettres)", "rénovation du hall"),
    "ascenseur": ("le remplacement de l'ascenseur", "nouvel ascenseur"),
    "visiophone": ("l'installation d'un visiophone", "visiophone"),
}
ETALEMENTS = [1, 2, 3]       # nombre d'années sur lesquelles on étale le paiement

# Plafond de hausse mensuelle acceptable, en % du revenu (HYPOTHÈSES, réglables)
MARGES = {"contre": 5.0, "partage": 6.0, "pour": 10.0}


def regles(scenario=None, marges=None):
    """Postes (coûts calés sur le budget du scénario) et plafonds par position."""
    scenario = scenario or {}
    budget = float(scenario.get("budget_annuel", 30000))
    urgent = scenario.get("urgent", "fuite au sous-sol, porte du local poubelles")
    postes = {k: {"libelle": LIBELLES[k][0].format(urgent=urgent), "court": LIBELLES[k][1],
                  "cout": round(budget * PARTS[k] / sum(PARTS.values()))} for k in PARTS}
    m = {**MARGES, **{k: float(v) for k, v in (marges or {}).items() if k in MARGES}}
    return {"postes": postes, "plafond": {k: v / 100 for k, v in m.items()}, "marges_pct": m}


REGLES_DEFAUT = regles()


def mensuel(p, postes, annees=1, R=REGLES_DEFAUT):
    """Hausse mensuelle des charges pour la persona p."""
    cout = sum(R["postes"][x]["cout"] for x in postes)
    return p["tantiemes"] / 1000 * cout / (12 * annees)


def profil(p, e, R=REGLES_DEFAUT):
    """Marge de négociation d'une persona, déduite de sa fiche et de sa position e."""
    pos = e["position"]
    sante = p.get("sante", "bonne sante") != "bonne sante" and p["etage"] >= 2
    haut = p["etage"] >= 3
    if pos == "pour":
        priorites = ["ascenseur", "hall", "visiophone"] if (haut or sante) else ["hall", "ascenseur", "visiophone"]
        indispensables = ["urgent", priorites[0]]
    else:
        priorites = ["ascenseur"] if sante else []
        indispensables = ["urgent"] + (["ascenseur"] if sante else [])
    plafond = R["plafond"][pos] * p["revenu_mensuel"]
    plafond = max(plafond, mensuel(p, ["urgent"], 1, R))      # tout le monde accepte l'urgent
    sacrifiables = [x for x in R["postes"] if x not in indispensables]
    return {"plafond": round(plafond, 2), "indispensables": indispensables, "priorites": priorites,
            "sacrifiables": sacrifiables}


def options(R=REGLES_DEFAUT):
    """Toutes les options : un ensemble de postes (toujours avec l'urgent) et un étalement."""
    autres = [x for x in R["postes"] if x != "urgent"]
    for k in range(len(autres) + 1):
        for combo in itertools.combinations(autres, k):
            for n in ETALEMENTS:
                yield (("urgent",) + combo, n)


def cout_option(option, R=REGLES_DEFAUT):
    return sum(R["postes"][x]["cout"] for x in option[0])


def acceptable(p, prof, option, R=REGLES_DEFAUT):
    postes, n = option
    return (all(x in postes for x in prof["indispensables"])
            and mensuel(p, postes, n, R) <= prof["plafond"] + 0.5)


def zone_accord(a, pa, b, pb, R=REGLES_DEFAUT):
    """Options acceptables pour les deux, de la plus ambitieuse à la plus modeste
    (plus de travaux d'abord, puis paiement le moins étalé)."""
    zone = [o for o in options(R) if acceptable(a, pa, o, R) and acceptable(b, pb, o, R)]
    return sorted(zone, key=lambda o: (-cout_option(o, R), o[1]))


def position_dans_zone(option, zone, R=REGLES_DEFAUT):
    """0 = l'option la plus modeste de la zone (avantage « contre »), 1 = la plus ambitieuse
    (avantage « pour »). None si l'option est hors zone ou la zone n'a qu'un coût."""
    if option is None or option not in zone:
        return None
    couts = [cout_option(o, R) / o[1] for o in zone]          # coût annualisé
    lo, hi = min(couts), max(couts)
    if hi == lo:
        return None
    return round((cout_option(option, R) / option[1] - lo) / (hi - lo), 3)


def texte_option(option, R=REGLES_DEFAUT):
    postes, n = option
    noms = [R["postes"][x]["court"] for x in postes]
    liste = noms[0] if len(noms) == 1 else ", ".join(noms[:-1]) + " et " + noms[-1]
    return f"{liste}, payés sur {n} an{'s' if n > 1 else ''}"


def euros(x):
    return f"{round(x):,}".replace(",", " ") + " €"


# ---------------------------------------------------------------------------
# Consignes
# ---------------------------------------------------------------------------
def consigne(p, autre, e, prof, scenario, commence=False, R=REGLES_DEFAUT):
    lignes_couts = "\n".join(
        f"- {v['libelle']} : {euros(v['cout'])} au total, soit {euros(mensuel(p, [k], 1, R))} par mois pour toi "
        f"si on paie sur 1 an" for k, v in R["postes"].items())
    tout = mensuel(p, list(R["postes"]), 1, R)
    indisp = ", ".join(R["postes"][x]["court"] for x in prof["indispensables"])
    sacri = ", ".join(R["postes"][x]["court"] for x in prof["sacrifiables"]) or "rien"
    autre_txt = 'une autre copropriétaire' if autre['sexe_fiche'] == 'femme' else 'un autre copropriétaire'
    return f"""Tu joues {p['prenom']} {p['nom']} dans une courte scène de théâtre réaliste.

TA FICHE (pour toi seul, ne la récite jamais)
{personas.texte_fiche(p)}

LA SITUATION
Lieu : {scenario['lieu']}.
Tu discutes avec {autre['prenom']} {autre['nom']}, {autre['age_annees']} ans, {autre_txt} de l'immeuble.
Le syndic propose quatre postes de travaux. L'assemblée peut les voter un par un, et le
paiement peut être étalé sur 1, 2 ou 3 ans (étaler divise la hausse mensuelle d'autant).
{lignes_couts}
Tout le projet sur 1 an : {euros(tout)} de plus par mois pour toi.

TA POSITION DE DÉPART
{e['objectif']}

TA MARGE DE NÉGOCIATION (secrète : ne l'annonce pas d'emblée)
- Tu ne peux pas accepter plus de {euros(prof['plafond'])} de hausse par mois.
- Tu tiens absolument à : {indisp}.
- Tu peux renoncer à : {sacri}.

LE BUT DE CETTE CONVERSATION
Vous voulez arriver ensemble à UNE proposition précise à présenter à l'assemblée générale.
- Fais des propositions concrètes : quels postes, payés sur combien d'années.
- Écoute celles de l'autre et fais des concessions sur ce qui compte moins pour toi.
- Si une proposition respecte ta marge, accepte-la, même si elle n'est pas idéale.
- Refuse ce qui dépasse ta marge, avec ton caractère, et propose autre chose.
- Quand vous êtes d'accord sur une proposition précise, termine ta réplique par [ACCORD].
  N'écris [ACCORD] que si tu acceptes vraiment la dernière proposition.

COMMENT JOUER
- Montre ta personnalité par ta façon de parler et de négocier, ne la décris jamais.
- Ne te présente pas, n'énumère pas tes caractéristiques, ne dis pas « en tant que… ».
- Une à trois phrases par réplique, langage oral et naturel. Vous vous vouvoyez.
- Écris uniquement ta réplique : pas de nom, pas de guillemets, pas de didascalies.
- Ne dis jamais que tu es une IA ou un personnage.
{"- C'est toi qui engages la conversation." if commence else ""}"""


def intervention_syndic(a, b, option, R=REGLES_DEFAUT):
    return (f"Si je peux me permettre : vous pourriez présenter ensemble {texte_option(option, R)}. "
            f"Cela ferait environ {euros(mensuel(a, *option, R))} de plus par mois pour {a['prenom']} "
            f"{a['nom']}, et {euros(mensuel(b, *option, R))} pour {b['prenom']} {b['nom']}.")


# ---------------------------------------------------------------------------
# Répliques du mode test (sans modèle de langage)
# ---------------------------------------------------------------------------
def scenario_test(a, b, zone, R=REGLES_DEFAUT):
    """Une négociation scriptée : elle aboutit si la zone d'accord existe, sinon elle échoue."""
    tout = (tuple(R["postes"]), 1)
    if not zone:
        return [
            (a, "Vous avez vu la convocation ? J'aimerais qu'on vote tout le projet.", False),
            (b, f"Tout le projet, c'est {euros(mensuel(b, *tout, R))} de plus par mois pour moi. Impossible.", False),
            (a, "Même étalé sur trois ans ? Je ne descendrai pas en dessous de ce qui compte pour moi.", False),
            (b, "Même étalé, c'est au-dessus de ce que je peux payer. On ne s'entendra pas ce soir.", False),
        ]
    ref = zone[0]
    essais = [(tuple(R["postes"]), 2), (tuple(x for x in R["postes"] if x != "visiophone"), 1)]
    inter = next((o for o in essais if o not in zone and o != ref), essais[-1])
    return [
        (a, "Vous avez vu la convocation ? J'aimerais qu'on vote tout le projet, l'immeuble le mérite.", False),
        (b, f"Tout le projet, c'est {euros(mensuel(b, *tout, R))} de plus par mois pour moi. Je ne peux pas.", False),
        (a, f"Et {texte_option(inter, R)} ? Ça vous ferait {euros(mensuel(b, *inter, R))}.", False),
        (b, "C'est encore trop. Les réparations urgentes, oui, mais je ne peux pas suivre au-delà comme ça.", False),
        (a, f"Alors proposons {texte_option(ref, R)}. Pour vous, ce serait {euros(mensuel(b, *ref, R))} par mois.", False),
        (b, f"{euros(mensuel(b, *ref, R))} par mois, je peux le tenir. D'accord, présentons ça ensemble.", True),
        (a, "Parfait, je le dirai au syndic avant l'assemblée.", True),
    ]


# ---------------------------------------------------------------------------
# Moteur de la négociation
# ---------------------------------------------------------------------------
BALISE = re.compile(r"\[\s*ACCORD\s*\]", re.I)
SYNDIC = "Le syndic"


def messages_pour(agent_nom, dialogue, debut):
    """Vue de l'agent : ses répliques = assistant, le reste = user (fusionné si consécutif)."""
    msgs = [{"role": "user", "content": "[La scène commence.]"}] if debut else []
    for nom, texte, _ in dialogue:
        role = "assistant" if nom == agent_nom else "user"
        contenu = texte if (role == "assistant" or nom != SYNDIC) else f"(Le syndic, qui passe : « {texte} »)"
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + contenu
        else:
            msgs.append({"role": role, "content": contenu})
    if msgs and msgs[0]["role"] == "assistant":
        msgs.insert(0, {"role": "user", "content": "[La scène commence.]"})
    return msgs


def _conclu(dialogue, nom_a, nom_b):
    """Accord conclu : les deux dernières répliques des agents, une chacun, le signalent."""
    derniers = [d for d in dialogue if d[0] in (nom_a, nom_b)][-2:]
    return len(derniers) == 2 and derniers[0][0] != derniers[1][0] and all(d[2] for d in derniers)


def jouer(a, b, ea, eb, client, nettoyer, scenario, tours=16, mediateur=True, verbeux=True,
          rappel=None, R=REGLES_DEFAUT):
    """a commence. Renvoie (dialogue, infos) ; dialogue = [(nom, texte, accord_signale)].
    rappel(nom, texte, accord) est appelé après chaque réplique (affichage en direct)."""
    pa, pb = profil(a, ea, R), profil(b, eb, R)
    zone = zone_accord(a, pa, b, pb, R)
    nom_a, nom_b = f"{a['prenom']} {a['nom']}", f"{b['prenom']} {b['nom']}"
    systemes = {nom_a: consigne(a, b, ea, pa, scenario, commence=True, R=R),
                nom_b: consigne(b, a, eb, pb, scenario, R=R)}
    dialogue, tour_syndic = [], None

    def dire(nom, texte, accord):
        dialogue.append((nom, texte, accord))
        if verbeux:
            print(f"{nom} : {texte}{'   [accord]' if accord else ''}\n", flush=True)
        if rappel:
            rappel(nom, texte, accord)

    if client.backend == "test":
        for p, texte, acc in scenario_test(a, b, zone, R):
            dire(f"{p['prenom']} {p['nom']}", texte, acc)
    else:
        agents = [(a, b, nom_a), (b, a, nom_b)]
        moment_syndic = (2 * tours) // 3
        for tour in range(tours):
            if mediateur and tour_syndic is None and tour >= moment_syndic and zone:
                dire(SYNDIC, intervention_syndic(a, b, zone[0], R), False)
                tour_syndic = len(dialogue)
            p, autre, nom = agents[tour % 2]
            msgs = messages_pour(nom, dialogue, debut=(tour == 0))
            if tour >= tours - 2:
                msgs[-1]["content"] += ("\n\n[Indication : la conversation doit se conclure. Si vous êtes "
                                        "d'accord sur une proposition précise, dis-le et termine par [ACCORD] ; "
                                        "sinon, constate le désaccord.]")
            brut = client.repondre(systemes[nom], msgs)
            accord = bool(BALISE.search(brut))
            texte = nettoyer(BALISE.sub("", brut), [p["prenom"], autre["prenom"]])
            dire(nom, texte, accord)
            if _conclu(dialogue, nom_a, nom_b):
                break

    conclu = _conclu(dialogue, nom_a, nom_b)
    return dialogue, {"profil_a": pa, "profil_b": pb, "zone": zone, "accord_signale": conclu,
                      "syndic": tour_syndic is not None, "tour_syndic": tour_syndic,
                      "tour_accord": len(dialogue) if conclu else None, "consignes": systemes}


# ---------------------------------------------------------------------------
# Ce qui a été décidé, et est-ce cohérent avec les fiches ?
# ---------------------------------------------------------------------------
MOTS = {"urgent": r"urgen|fuite|poubelle|répar", "hall": r"\bhall", "ascenseur": r"ascenseur",
        "visiophone": r"visio"}


def _heuristique(textes):
    """Repère les postes et l'étalement cités dans les dernières répliques."""
    t = " ".join(textes).lower()
    postes = tuple(k for k in PARTS if re.search(MOTS[k], t))
    m = re.search(r"(?:sur|en)\s+(un|deux|trois|1|2|3)\s+ans?", t)
    n = 1
    if m:
        g = m.group(1)
        n = {"un": 1, "deux": 2, "trois": 3}.get(g) or int(g)
    if "urgent" not in postes:
        postes = ("urgent",) + postes
    return postes, n


def extraire_accord(client, dialogue, infos):
    """Décision finale : (option, méthode). Par un « secrétaire de séance » (le LLM) si
    possible, sinon par repérage des mots-clés dans les dernières répliques."""
    if not infos["accord_signale"]:
        return None, None
    if client.backend == "test":
        return infos["zone"][0], "script"
    transcription = "\n".join(f"{n} : {t}" for n, t, _ in dialogue)
    systeme = ("Tu es secrétaire de séance. Tu lis une conversation et tu notes la proposition finale "
               "sur laquelle les deux copropriétaires se sont mis d'accord. Réponds uniquement en JSON.")
    question = (f"{transcription}\n\nRéponds en JSON, sans rien d'autre : "
                '{"postes": [liste parmi "urgent", "hall", "ascenseur", "visiophone"], '
                '"etalement_ans": 1, 2 ou 3}')
    try:
        brut = client.repondre(systeme, [{"role": "user", "content": question}])
        m = re.search(r"\{.*\}", brut, re.S)
        d = json.loads(m.group(0))
        postes = tuple(x for x in PARTS if x in d.get("postes", []))
        n = int(d.get("etalement_ans", 1))
        if postes and n in ETALEMENTS:
            if "urgent" not in postes:
                postes = ("urgent",) + postes
            return (postes, n), "secretaire"
    except Exception:                                         # noqa: BLE001
        pass
    return _heuristique([t for _, t, _ in dialogue[-4:]]), "mots_cles"


def bilan(a, b, infos, option, R=REGLES_DEFAUT):
    """L'accord respecte-t-il les limites calculées des deux personas ?"""
    if option is None:
        return {"accord": False, "zone_accord_existe": bool(infos["zone"])}
    return {
        "accord": True,
        "proposition": texte_option(option, R),
        f"hausse_{a['prenom']}": euros(mensuel(a, *option, R)),
        f"hausse_{b['prenom']}": euros(mensuel(b, *option, R)),
        f"respecte_limites_{a['prenom']}": bool(acceptable(a, infos["profil_a"], option, R)),
        f"respecte_limites_{b['prenom']}": bool(acceptable(b, infos["profil_b"], option, R)),
        "syndic_intervenu": infos["syndic"],
    }