"""
Population synthétique - Partie 2 : négocier jusqu'à un terrain d'entente
=========================================================================

Pour qu'un compromis soit possible, il faut :
  1. quelque chose à négocier : le projet est découpé en POSTES votables
     séparément, et le paiement peut être ÉTALÉ sur 1, 2 ou 3 ans ;
  2. une marge de manœuvre pour chaque persona, CALCULÉE depuis sa fiche :
     un plafond mensuel, les postes auxquels elle tient absolument, ceux
     qu'elle peut sacrifier ;
  3. vérifier qu'une ZONE D'ACCORD existe : au moins une option (postes +
     étalement) acceptable pour les deux.

Le dialogue s'arrête quand les deux agents signalent l'accord ([ACCORD]).
S'ils s'enlisent, le syndic propose un compromis tiré de la zone d'accord.
À la fin, on extrait l'accord et on VÉRIFIE qu'il respecte les limites des deux.
"""

import itertools
import json
import re

import personas

# ---------------------------------------------------------------------------
# Ce qui se négocie
# ---------------------------------------------------------------------------
POSTES = {
    "urgent":     {"libelle": "les réparations urgentes (fuite au sous-sol, porte du local poubelles)",
                   "court": "réparations urgentes", "cout": 4000},
    "hall":       {"libelle": "la rénovation du hall (éclairage, carrelage, boîtes aux lettres)",
                   "court": "rénovation du hall", "cout": 8000},
    "ascenseur":  {"libelle": "le remplacement de l'ascenseur", "court": "nouvel ascenseur", "cout": 15000},
    "visiophone": {"libelle": "l'installation d'un visiophone", "court": "visiophone", "cout": 3000},
}
ETALEMENTS = [1, 2, 3]       # nombre d'années sur lesquelles on étale le paiement

# Plafond de hausse mensuelle acceptable, en part du revenu (HYPOTHÈSES)
PLAFOND = {"contre": 0.05, "partage": 0.06, "pour": 0.10}


def mensuel(p, postes, annees=1):
    """Hausse mensuelle des charges pour la persona p."""
    cout = sum(POSTES[x]["cout"] for x in postes)
    return p["tantiemes"] / 1000 * cout / (12 * annees)


def profil(p, e):
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
    plafond = PLAFOND[pos] * p["revenu_mensuel"]
    plafond = max(plafond, mensuel(p, ["urgent"]))      # tout le monde accepte l'urgent
    sacrifiables = [x for x in POSTES if x not in indispensables]
    return {"plafond": plafond, "indispensables": indispensables, "priorites": priorites,
            "sacrifiables": sacrifiables}


def options():
    """Toutes les options : un ensemble de postes (toujours avec l'urgent) et un étalement."""
    autres = [x for x in POSTES if x != "urgent"]
    for k in range(len(autres) + 1):
        for combo in itertools.combinations(autres, k):
            for n in ETALEMENTS:
                yield (("urgent",) + combo, n)


def acceptable(p, prof, option):
    postes, n = option
    return (all(x in postes for x in prof["indispensables"])
            and mensuel(p, postes, n) <= prof["plafond"] + 0.5)


def zone_accord(a, pa, b, pb):
    """Options acceptables pour les deux, de la plus ambitieuse à la plus modeste
    (plus de travaux d'abord, puis paiement le moins étalé)."""
    zone = [o for o in options() if acceptable(a, pa, o) and acceptable(b, pb, o)]
    return sorted(zone, key=lambda o: (-sum(POSTES[x]["cout"] for x in o[0]), o[1]))


def texte_option(option):
    postes, n = option
    noms = [POSTES[x]["court"] for x in postes]
    liste = noms[0] if len(noms) == 1 else ", ".join(noms[:-1]) + " et " + noms[-1]
    return f"{liste}, payés sur {n} an{'s' if n > 1 else ''}"


def euros(x):
    return f"{round(x):,}".replace(",", " ") + " €"


# ---------------------------------------------------------------------------
# Consignes
# ---------------------------------------------------------------------------
def consigne(p, autre, e, prof, scenario, commence=False):
    lignes_couts = "\n".join(
        f"- {v['libelle']} : {euros(v['cout'])} au total, soit {euros(mensuel(p, [k]))} par mois pour toi "
        f"si on paie sur 1 an" for k, v in POSTES.items())
    tout = mensuel(p, list(POSTES))
    indisp = ", ".join(POSTES[x]["court"] for x in prof["indispensables"])
    sacri = ", ".join(POSTES[x]["court"] for x in prof["sacrifiables"]) or "rien"
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


def intervention_syndic(a, b, option):
    return (f"Si je peux me permettre : vous pourriez présenter ensemble {texte_option(option)}. "
            f"Cela ferait environ {euros(mensuel(a, *option))} de plus par mois pour {a['prenom']} "
            f"{a['nom']}, et {euros(mensuel(b, *option))} pour {b['prenom']} {b['nom']}.")


# ---------------------------------------------------------------------------
# Répliques du mode test (sans modèle de langage)
# ---------------------------------------------------------------------------
def scenario_test(a, b, zone):
    """Une négociation scriptée qui aboutit, pour vérifier la chaîne."""
    ref = zone[0]
    tout = (tuple(POSTES), 1)
    # une concession intermédiaire, encore refusée (hors de la zone d'accord)
    essais = [(tuple(POSTES), 2), (tuple(x for x in POSTES if x != "visiophone"), 1)]
    inter = next((o for o in essais if o not in zone and o != ref), essais[-1])
    return [
        (a, "Vous avez vu la convocation ? J'aimerais qu'on vote tout le projet, l'immeuble le mérite.", False),
        (b, f"Tout le projet, c'est {euros(mensuel(b, *tout))} de plus par mois pour moi. Je ne peux pas.", False),
        (a, f"Et {texte_option(inter)} ? Ça vous ferait {euros(mensuel(b, *inter))}.", False),
        (b, "C'est encore trop. Les réparations urgentes, oui, mais je ne peux pas suivre au-delà comme ça.", False),
        (a, f"Alors proposons {texte_option(ref)}. Pour vous, ce serait {euros(mensuel(b, *ref))} par mois.", False),
        (b, f"{euros(mensuel(b, *ref))} par mois, je peux le tenir. D'accord, présentons ça ensemble.", True),
        (a, "Parfait, je le dirai au syndic avant l'assemblée.", True),
    ]


# ---------------------------------------------------------------------------
# Moteur de la négociation
# ---------------------------------------------------------------------------
BALISE = re.compile(r"\[\s*ACCORD\s*\]", re.I)


def messages_pour(agent_nom, dialogue, debut):
    """Vue de l'agent : ses répliques = assistant, le reste = user (fusionné si consécutif)."""
    msgs = [{"role": "user", "content": "[La scène commence.]"}] if debut else []
    for nom, texte, _ in dialogue:
        role = "assistant" if nom == agent_nom else "user"
        contenu = texte if (role == "assistant" or not nom.startswith("Le syndic")) else f"(Le syndic, qui passe : « {texte} »)"
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + contenu
        else:
            msgs.append({"role": role, "content": contenu})
    if msgs and msgs[0]["role"] == "assistant":
        msgs.insert(0, {"role": "user", "content": "[La scène commence.]"})
    return msgs


def jouer(a, b, ea, eb, client, nettoyer, scenario, tours=16, mediateur=True, verbeux=True):
    """a commence. Renvoie (dialogue, infos) ; dialogue = [(nom, texte, accord_signale)]."""
    pa, pb = profil(a, ea), profil(b, eb)
    zone = zone_accord(a, pa, b, pb)
    nom_a, nom_b = f"{a['prenom']} {a['nom']}", f"{b['prenom']} {b['nom']}"
    dialogue = []

    def dire(nom, texte, accord):
        dialogue.append((nom, texte, accord))
        if verbeux:
            print(f"{nom} : {texte}{'   [accord]' if accord else ''}\n", flush=True)

    if client.backend == "test":
        for p, texte, acc in scenario_test(a, b, zone):
            dire(f"{p['prenom']} {p['nom']}", texte, acc)
    else:
        agents = [(a, b, nom_a, consigne(a, b, ea, pa, scenario, commence=True)),
                  (b, a, nom_b, consigne(b, a, eb, pb, scenario))]
        moment_syndic = (2 * tours) // 3
        syndic_passe = False
        for tour in range(tours):
            if mediateur and not syndic_passe and tour >= moment_syndic and zone:
                dire("Le syndic", intervention_syndic(a, b, zone[0]), False)
                syndic_passe = True
            p, autre, nom, systeme = agents[tour % 2]
            msgs = messages_pour(nom, dialogue, debut=(tour == 0))
            if tour >= tours - 2:
                msgs[-1]["content"] += ("\n\n[Indication : la conversation doit se conclure. Si vous êtes "
                                        "d'accord sur une proposition précise, dis-le et termine par [ACCORD] ; "
                                        "sinon, constate le désaccord.]")
            brut = client.repondre(systeme, msgs)
            accord = bool(BALISE.search(brut))
            texte = nettoyer(BALISE.sub("", brut), [p["prenom"], autre["prenom"]])
            dire(nom, texte, accord)
            # Accord conclu quand les deux dernières répliques des deux agents le signalent
            derniers = [d for d in dialogue if d[0] in (nom_a, nom_b)][-2:]
            if len(derniers) == 2 and derniers[0][0] != derniers[1][0] and all(d[2] for d in derniers):
                break

    agents_seuls = [d for d in dialogue if d[0] in (nom_a, nom_b)][-2:]
    conclu = len(agents_seuls) == 2 and agents_seuls[0][0] != agents_seuls[1][0] and all(d[2] for d in agents_seuls)
    return dialogue, {"profil_a": pa, "profil_b": pb, "zone": zone, "accord_signale": conclu,
                      "syndic": any(d[0] == "Le syndic" for d in dialogue)}


# ---------------------------------------------------------------------------
# Ce qui a été décidé, et est-ce cohérent avec les fiches ?
# ---------------------------------------------------------------------------
MOTS = {"urgent": r"urgen|fuite|poubelle|répar", "hall": r"\bhall", "ascenseur": r"ascenseur",
        "visiophone": r"visio"}


def _heuristique(textes):
    """Repère les postes et l'étalement cités dans les dernières répliques."""
    t = " ".join(textes).lower()
    postes = tuple(k for k in POSTES if re.search(MOTS[k], t))
    m = re.search(r"(?:sur|en)\s+(un|deux|trois|1|2|3)\s+ans?", t)
    n = 1
    if m:
        g = m.group(1)
        n = {"un": 1, "deux": 2, "trois": 3}.get(g) or int(g)
    if "urgent" not in postes:
        postes = ("urgent",) + postes
    return postes, n


def extraire_accord(client, dialogue, infos):
    """Décision finale : par un « secrétaire de séance » (le LLM) si possible, sinon par
    repérage des mots-clés dans les dernières répliques."""
    if not infos["accord_signale"]:
        return None
    if client.backend == "test":
        return infos["zone"][0]
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
        postes = tuple(x for x in POSTES if x in d.get("postes", []))
        n = int(d.get("etalement_ans", 1))
        if postes and n in ETALEMENTS:
            if "urgent" not in postes:
                postes = ("urgent",) + postes
            return postes, n
    except Exception:
        pass
    return _heuristique([t for _, t, _ in dialogue[-4:]])


def bilan(a, b, infos, option):
    """L'accord respecte-t-il les limites calculées des deux personas ?"""
    if option is None:
        return {"accord": False, "zone_accord_existe": bool(infos["zone"])}
    return {
        "accord": True,
        "proposition": texte_option(option),
        f"hausse_{a['prenom']}": euros(mensuel(a, *option)),
        f"hausse_{b['prenom']}": euros(mensuel(b, *option)),
        f"respecte_limites_{a['prenom']}": bool(acceptable(a, infos["profil_a"], option)),
        f"respecte_limites_{b['prenom']}": bool(acceptable(b, infos["profil_b"], option)),
        "syndic_intervenu": infos["syndic"],
    }