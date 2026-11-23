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


def zone_groupe(agents, profils, R=REGLES_DEFAUT):
    """Options acceptables pour TOUS les agents, de la plus ambitieuse à la plus modeste
    (plus de travaux d'abord, puis paiement le moins étalé)."""
    zone = [o for o in options(R) if all(acceptable(p, pr, o, R) for p, pr in zip(agents, profils))]
    return sorted(zone, key=lambda o: (-cout_option(o, R), o[1]))


def zone_accord(a, pa, b, pb, R=REGLES_DEFAUT):
    """Options acceptables pour les deux (cas de deux agents)."""
    return zone_groupe([a, b], [pa, pb], R)


def cout_annuel(option, R=REGLES_DEFAUT):
    """Coût du projet par an (toute la copropriété) : l'échelle commune pour comparer les propositions."""
    return cout_option(option, R) / option[1]


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
def _presenter(autres):
    """« X, 52 ans, une autre copropriétaire de l'immeuble » ; liste pour 2 interlocuteurs ou plus."""
    def un(a):
        qui = 'une autre copropriétaire' if a['sexe_fiche'] == 'femme' else 'un autre copropriétaire'
        return f"{a['prenom']} {a['nom']}, {a['age_annees']} ans, {qui} de l'immeuble"
    if len(autres) == 1:
        return un(autres[0])
    return "; ".join(un(a) for a in autres[:-1]) + " ; et " + un(autres[-1])


def consigne(p, autres, e, prof, scenario, commence=False, R=REGLES_DEFAUT):
    """Prompt système d'un agent. `autres` : la ou les autres personas (une seule = scène à deux)."""
    if isinstance(autres, dict) or hasattr(autres, "keys"):          # compatibilité : un seul interlocuteur
        autres = [autres]
    groupe = len(autres) > 1
    lignes_couts = "\n".join(
        f"- {v['libelle']} : {euros(v['cout'])} au total, soit {euros(mensuel(p, [k], 1, R))} par mois pour toi "
        f"si on paie sur 1 an" for k, v in R["postes"].items())
    tout = mensuel(p, list(R["postes"]), 1, R)
    indisp = ", ".join(R["postes"][x]["court"] for x in prof["indispensables"])
    sacri = ", ".join(R["postes"][x]["court"] for x in prof["sacrifiables"]) or "rien"
    ensemble = "à trois" if len(autres) == 2 else "ensemble"
    regle_groupe = ("\n- Une proposition n'est retenue que si TOUS l'acceptent : tiens compte de chacun."
                    "\n- Les répliques des autres sont précédées de leur nom ; adresse-toi à qui tu veux."
                    if groupe else "")
    return f"""Tu joues {p['prenom']} {p['nom']} dans une courte scène de théâtre réaliste.

TA FICHE (pour toi seul, ne la récite jamais)
{personas.texte_fiche(p)}

LA SITUATION
Lieu : {scenario['lieu']}.
Tu discutes avec {_presenter(autres)}.
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
Vous voulez arriver {ensemble} à UNE proposition précise à présenter à l'assemblée générale.
- Fais des propositions concrètes : quels postes, payés sur combien d'années.
- Écoute celles des autres et fais des concessions sur ce qui compte moins pour toi.
- Si une proposition respecte ta marge, accepte-la, même si elle n'est pas idéale.
- Refuse ce qui dépasse ta marge, avec ton caractère, et propose autre chose.
- Quand vous êtes d'accord sur une proposition précise, termine ta réplique par [ACCORD].
  N'écris [ACCORD] que si tu acceptes vraiment la dernière proposition.{regle_groupe}

COMMENT JOUER
- Montre ta personnalité par ta façon de parler et de négocier, ne la décris jamais.
- Ne te présente pas, n'énumère pas tes caractéristiques, ne dis pas « en tant que… ».
- Une à trois phrases par réplique, langage oral et naturel. Vous vous vouvoyez.
- Écris uniquement ta réplique : pas de nom, pas de guillemets, pas de didascalies.
- Ne dis jamais que tu es une IA ou un personnage.
{"- C'est toi qui engages la conversation." if commence else ""}"""


def intervention_syndic(agents, option, R=REGLES_DEFAUT, *anciens):
    """Le compromis proposé par le syndic. Accepte aussi l'ancienne forme (a, b, option)."""
    if not isinstance(agents, (list, tuple)):                 # ancienne signature : (a, b, option, R)
        agents, option, R = [agents, option], R, (anciens[0] if anciens else REGLES_DEFAUT)
    parts = [f"{euros(mensuel(p, *option, R))} pour {p['prenom']} {p['nom']}" for p in agents]
    liste = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " et " + parts[-1]
    qui = "ensemble" if len(agents) == 2 else "tous les trois" if len(agents) == 3 else "ensemble"
    return (f"Si je peux me permettre : vous pourriez présenter {qui} {texte_option(option, R)}. "
            f"Cela ferait environ {liste} de plus par mois.")


# ---------------------------------------------------------------------------
# Répliques du mode test (sans modèle de langage)
# ---------------------------------------------------------------------------
def scenario_test(agents, zone, R=REGLES_DEFAUT, *anciens):
    """Une négociation scriptée : elle aboutit si la zone d'accord existe, sinon elle échoue.
    Accepte aussi l'ancienne forme (a, b, zone)."""
    if not isinstance(agents, (list, tuple)):
        agents, zone, R = [agents, zone], R, (anciens[0] if anciens else REGLES_DEFAUT)
    a, b = agents[0], agents[1]
    c = agents[2] if len(agents) > 2 else None
    tout = (tuple(R["postes"]), 1)
    if not zone:
        lignes = [
            (a, "Vous avez vu la convocation ? J'aimerais qu'on vote tout le projet.", False),
            (b, f"Tout le projet, c'est {euros(mensuel(b, *tout, R))} de plus par mois pour moi. Impossible.", False),
        ]
        if c is not None:
            lignes.append((c, "Je suis entre les deux, mais là je ne vois pas d'issue.", False))
        lignes += [
            (a, "Même étalé sur trois ans ? Je ne descendrai pas en dessous de ce qui compte pour moi.", False),
            (b, "Même étalé, c'est au-dessus de ce que je peux payer. On ne s'entendra pas ce soir.", False),
        ]
        return lignes
    ref = zone[0]
    essais = [(tuple(R["postes"]), 2), (tuple(x for x in R["postes"] if x != "visiophone"), 1)]
    inter = next((o for o in essais if o not in zone and o != ref), essais[-1])
    lignes = [
        (a, f"Vous avez vu la convocation ? Je propose tout le projet sur un an, l'immeuble le mérite.", False),
        (b, f"Ça me ferait {euros(mensuel(b, *tout, R))} de plus par mois. Je ne voterais que les réparations "
            f"urgentes, sur un an.", False),
    ]
    if c is not None:
        lignes.append((c, f"Et {texte_option(inter, R)} ? Ce serait un premier pas.", False))
    lignes += [
        (a, f"Alors {texte_option(inter, R)}. Ça vous ferait {euros(mensuel(b, *inter, R))}.", False),
        (b, "C'est encore trop. Les réparations urgentes, oui, mais je ne peux pas suivre au-delà comme ça.", False),
        (a, f"Alors proposons {texte_option(ref, R)}. Pour vous, ce serait {euros(mensuel(b, *ref, R))} par mois.", False),
        (b, f"{texte_option(ref, R).capitalize()}, je peux le tenir. D'accord.", True),
    ]
    if c is not None:
        lignes.append((c, f"Moi aussi, {texte_option(ref, R)} me convient.", True))
    lignes.append((a, "Parfait, je le dirai au syndic avant l'assemblée.", True))
    return lignes


# ---------------------------------------------------------------------------
# Moteur de la négociation
# ---------------------------------------------------------------------------
BALISE = re.compile(r"\[\s*ACCORD\s*\]", re.I)
SYNDIC = "Le syndic"


def messages_pour(agent_nom, dialogue, debut, noms_visibles=False):
    """Vue de l'agent : ses répliques = assistant, le reste = user (fusionné si consécutif).
    noms_visibles : préfixer les répliques des autres par leur nom (scène à plus de deux)."""
    msgs = [{"role": "user", "content": "[La scène commence.]"}] if debut else []
    for nom, texte, _ in dialogue:
        role = "assistant" if nom == agent_nom else "user"
        if role == "assistant":
            contenu = texte
        elif nom == SYNDIC:
            contenu = f"(Le syndic, qui passe : « {texte} »)"
        else:
            contenu = f"{nom} : {texte}" if noms_visibles else texte
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + contenu
        else:
            msgs.append({"role": role, "content": contenu})
    if msgs and msgs[0]["role"] == "assistant":
        msgs.insert(0, {"role": "user", "content": "[La scène commence.]"})
    return msgs


def _conclu(dialogue, noms):
    """Accord conclu : les dernières répliques de chaque agent, une chacun, le signalent toutes."""
    derniers = [d for d in dialogue if d[0] in noms][-len(noms):]
    return (len(derniers) == len(noms) and len({d[0] for d in derniers}) == len(noms)
            and all(d[2] for d in derniers))


def jouer_groupe(agents, enjeux, client, nettoyer, scenario, tours=16, mediateur=True, verbeux=True,
                 rappel=None, R=REGLES_DEFAUT):
    """Négociation entre 2 agents ou plus ; le premier commence, puis chacun parle à tour de rôle.
    Renvoie (dialogue, infos) ; dialogue = [(nom, texte, accord_signale)]."""
    profils = [profil(p, e, R) for p, e in zip(agents, enjeux)]
    zone = zone_groupe(agents, profils, R)
    noms = [f"{p['prenom']} {p['nom']}" for p in agents]
    systemes = {nom: consigne(p, [q for q in agents if q is not p], e, pr, scenario, commence=(k == 0), R=R)
                for k, (nom, p, e, pr) in enumerate(zip(noms, agents, enjeux, profils))}
    dialogue, tour_syndic = [], None

    def dire(nom, texte, accord):
        dialogue.append((nom, texte, accord))
        if verbeux:
            print(f"{nom} : {texte}{'   [accord]' if accord else ''}\n", flush=True)
        if rappel:
            rappel(nom, texte, accord)

    if client.backend == "test":
        for p, texte, acc in scenario_test(list(agents), zone, R):
            dire(f"{p['prenom']} {p['nom']}", texte, acc)
    else:
        moment_syndic = (2 * tours) // 3
        for tour in range(tours):
            if mediateur and tour_syndic is None and tour >= moment_syndic and zone:
                dire(SYNDIC, intervention_syndic(list(agents), zone[0], R), False)
                tour_syndic = len(dialogue)
            k = tour % len(agents)
            p, nom = agents[k], noms[k]
            msgs = messages_pour(nom, dialogue, debut=(tour == 0), noms_visibles=len(agents) > 2)
            if tour >= tours - len(agents):
                msgs[-1]["content"] += ("\n\n[Indication : la conversation doit se conclure. Si vous êtes "
                                        "d'accord sur une proposition précise, dis-le et termine par [ACCORD] ; "
                                        "sinon, constate le désaccord.]")
            brut = client.repondre(systemes[nom], msgs)
            accord = bool(BALISE.search(brut))
            texte = nettoyer(BALISE.sub("", brut), [q["prenom"] for q in agents])
            dire(nom, texte, accord)
            if _conclu(dialogue, noms):
                break

    conclu = _conclu(dialogue, noms)
    infos = {"profils": profils, "zone": zone, "accord_signale": conclu,
             "syndic": tour_syndic is not None, "tour_syndic": tour_syndic,
             "tour_accord": len(dialogue) if conclu else None, "consignes": systemes}
    if len(agents) == 2:                                      # noms historiques (bilan, ancien code)
        infos["profil_a"], infos["profil_b"] = profils
    return dialogue, infos


def jouer(a, b, ea, eb, client, nettoyer, scenario, tours=16, mediateur=True, verbeux=True,
          rappel=None, R=REGLES_DEFAUT):
    """Négociation à deux (a commence)."""
    return jouer_groupe([a, b], [ea, eb], client, nettoyer, scenario, tours, mediateur, verbeux, rappel, R)


# ---------------------------------------------------------------------------
# Ce qui a été décidé, et est-ce cohérent avec les fiches ?
# ---------------------------------------------------------------------------
MOTS = {"urgent": r"urgen|fuite|poubelle|répar", "hall": r"\bhall", "ascenseur": r"ascenseur",
        "visiophone": r"visio"}
TOUT = r"tout le projet|l'ensemble du projet|tous les travaux|les quatre postes"


def _heuristique(textes):
    """Repère les postes et l'étalement cités dans les dernières répliques."""
    t = " ".join(textes).lower()
    postes = tuple(k for k in PARTS if re.search(MOTS[k], t))
    if re.search(TOUT, t):
        postes = tuple(PARTS)
    m = re.search(r"(?:sur|en)\s+(un|deux|trois|1|2|3)\s+ans?", t)
    n = 1
    if m:
        g = m.group(1)
        n = {"un": 1, "deux": 2, "trois": 3}.get(g) or int(g)
    if "urgent" not in postes:
        postes = ("urgent",) + postes
    return postes, n


def _option_ligne(texte):
    """Proposition contenue dans UNE réplique (repérage par mots-clés) ; None si elle n'en contient pas."""
    t = texte.lower()
    if not (re.search(TOUT, t) or any(re.search(MOTS[k], t) for k in PARTS if k != "urgent")
            or re.search(r"(?:sur|en)\s+(un|deux|trois|1|2|3)\s+ans?", t)):
        return None
    return _heuristique([texte])


def extraire_accord(client, dialogue, infos):
    """Décision finale : (option, méthode). Par un « secrétaire de séance » (le LLM) si
    possible, sinon par repérage des mots-clés dans les dernières répliques."""
    if not infos["accord_signale"]:
        return None, None
    if client.backend == "test":
        return infos["zone"][0], "script"
    transcription = "\n".join(f"{n} : {t}" for n, t, _ in dialogue)
    systeme = ("Tu es secrétaire de séance. Tu lis une conversation et tu notes la proposition finale "
               "sur laquelle les copropriétaires se sont mis d'accord. Réponds uniquement en JSON.")
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


# ---------------------------------------------------------------------------
# Suivi des propositions : qui propose quoi, réplique après réplique
# ---------------------------------------------------------------------------
def _option_json(d):
    if not isinstance(d, dict):
        return None
    postes = tuple(x for x in PARTS if x in (d.get("postes") or []))
    try:
        n = int(d.get("etalement_ans") or 1)
    except (TypeError, ValueError):
        n = 1
    if not postes or n not in ETALEMENTS:
        return None
    if "urgent" not in postes:
        postes = ("urgent",) + postes
    return postes, n


def suivre_propositions(client, dialogue):
    """Pour chaque réplique, la proposition que le locuteur avance ou défend (None s'il n'en
    formule pas). Lecture par le modèle (un seul appel) si possible, sinon par mots-clés.
    Renvoie (liste d'options ou None, méthode)."""
    par_mots = [None if nom == SYNDIC else _option_ligne(texte) for nom, texte, _ in dialogue]
    if client.backend == "test":
        return par_mots, "mots_cles"
    numerotee = "\n".join(f"{k + 1}. {n} : {t}" for k, (n, t, _) in enumerate(dialogue))
    systeme = ("Tu es secrétaire de séance. Pour chaque réplique numérotée, tu notes la proposition de "
               "travaux que le locuteur avance, défend ou accepte. Réponds uniquement en JSON.")
    question = (f"{numerotee}\n\nRéponds par une liste JSON avec un élément par réplique, dans l'ordre : "
                '{"n": numéro, "postes": [parmi "urgent", "hall", "ascenseur", "visiophone"], '
                '"etalement_ans": 1, 2 ou 3} ; ou {"n": numéro, "postes": null} si la réplique ne contient '
                "aucune proposition, même implicite.")
    try:
        brut = client.repondre(systeme, [{"role": "user", "content": question}])
        m = re.search(r"\[.*\]", brut, re.S)
        liste = json.loads(m.group(0))
        res = [None] * len(dialogue)
        for d in liste:
            k = int(d.get("n", 0)) - 1
            if 0 <= k < len(dialogue) and dialogue[k][0] != SYNDIC:
                res[k] = _option_json(d)
        if sum(o is not None for o in res) >= sum(o is not None for o in par_mots) // 2:
            return res, "secretaire"
    except Exception:                                         # noqa: BLE001
        pass
    return par_mots, "mots_cles"


def concessions(agents, enjeux, dialogue, propositions, R=REGLES_DEFAUT, option_finale=None):
    """Pour chaque agent : première et dernière proposition (coût du projet par an), et la
    concession = le chemin fait vers les autres, en € par an et en part du budget annuel.
    Un « pour » concède en baissant le coût, un « contre » en l'augmentant ; pour un
    « partagé », sans camp, c'est le chemin parcouru dans un sens ou dans l'autre."""
    budget = sum(v["cout"] for v in R["postes"].values())
    res = []
    for p, e in zip(agents, enjeux):
        nom = f"{p['prenom']} {p['nom']}"
        points = [(k, cout_annuel(o, R)) for k, ((n, _, _), o) in enumerate(zip(dialogue, propositions))
                  if n == nom and o is not None]
        premiere = points[0][1] if points else None
        derniere = cout_annuel(option_finale, R) if option_finale else (points[-1][1] if points else None)
        if premiere is None or derniere is None:
            res.append({"nom": nom, "position": e["position"], "premiere": premiere, "finale": derniere,
                        "concession_eur": None, "concession_part": None, "propositions": len(points)})
            continue
        if e["position"] == "pour":
            delta = premiere - derniere
        elif e["position"] == "contre":
            delta = derniere - premiere
        else:                                   # partagé : pas de camp, on mesure le chemin parcouru
            delta = abs(derniere - premiere)
        res.append({"nom": nom, "position": e["position"], "premiere": round(premiere), "finale": round(derniere),
                    "concession_eur": round(delta), "concession_part": round(delta / budget, 3),
                    "propositions": len(points)})
    return res


def bilan(a, b, infos, option, R=REGLES_DEFAUT):
    """L'accord respecte-t-il les limites calculées des deux personas ? (scène à deux)"""
    if option is None:
        return {"accord": False, "zone_accord_existe": bool(infos["zone"])}
    pa, pb = infos.get("profil_a") or infos["profils"][0], infos.get("profil_b") or infos["profils"][1]
    return {
        "accord": True,
        "proposition": texte_option(option, R),
        f"hausse_{a['prenom']}": euros(mensuel(a, *option, R)),
        f"hausse_{b['prenom']}": euros(mensuel(b, *option, R)),
        f"respecte_limites_{a['prenom']}": bool(acceptable(a, pa, option, R)),
        f"respecte_limites_{b['prenom']}": bool(acceptable(b, pb, option, R)),
        "syndic_intervenu": infos["syndic"],
    }