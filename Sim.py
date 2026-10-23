"""
Simule les réponses d'une population à une question via Ollama.

Usage:
    python simulate.py context.txt "Votre question ?" [--csv population_finale.csv]
                       [--model llama3] [--output result.txt] [--limit N]

context.txt (une ligne par attribut) :
    A0 : {Moins de 30 ans, 30-60 ans, Plus de 60 ans}
    ...
La valeur 0 correspond au 1er élément, 1 au 2e, etc.
"""
import argparse
import csv
import json
import re
import sys
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434/api/generate"


def parse_context(path):
    """Retourne {'A0': ['Val1', 'Val2', ...], ...}"""
    mapping = {}
    pattern = re.compile(r"^\s*(A\d+)\s*:\s*\{(.*)\}\s*$")
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            m = pattern.match(line)
            if not m:
                sys.exit(f"Erreur context.txt ligne {lineno} : format invalide -> {line.strip()}")
            mapping[m.group(1)] = [v.strip() for v in m.group(2).split(",")]
    return mapping


def load_population(path):
    """Lit le CSV"""
    with open(path, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.reader(f) if r]
    if not rows:
        sys.exit("Le fichier CSV est vide.")
    first = [c.strip() for c in rows[0]]
    if all(re.fullmatch(r"A\d+", c) for c in first):
        header, data = first, rows[1:]
    else:
        header = [f"A{i}" for i in range(len(first))]
        data = rows
    return header, [[int(float(c)) for c in r] for r in data]


def build_prompt(index, header, row, mapping, question):
    parts = []
    for attr, value in zip(header, row):
        options = mapping.get(attr)
        if options is None:
            label = str(value)
        elif 0 <= value < len(options):
            label = options[value]
        else:
            sys.exit(f"Valeur {value} hors limites pour {attr} (options : {options})")
        parts.append(f"{attr}[{label}]")
    return (
        f'Vous êtes "individu{index}". '
        f"Vos attributs sont : {', '.join(parts)}. "
        f"Répondez en 2-3 phrases à cette question : {question}"
    )


def ask_ollama(prompt, model):
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))["response"].strip()
    except urllib.error.URLError as e:
        sys.exit(f"Impossible de contacter Ollama ({e}). Lancez 'ollama serve' et vérifiez le modèle '{model}'.")


def main():
    ap = argparse.ArgumentParser(description="Simulation d'une population avec Ollama")
    ap.add_argument("context", help="Fichier context.txt décrivant les attributs")
    ap.add_argument("question", help="Question posée à la population")
    ap.add_argument("--csv", default="population_finale.csv", help="CSV de la population")
    ap.add_argument("--model", default="llama3", help="Modèle Ollama (défaut : llama3)")
    ap.add_argument("--output", default="result.txt", help="Fichier de sortie")
    ap.add_argument("--limit", type=int, default=None,
                    help="Ne traiter que les n premiers individus (défaut : tous)")
    args = ap.parse_args()

    mapping = parse_context(args.context)
    header, population = load_population(args.csv)
    if args.limit is not None:
        if args.limit < 1:
            sys.exit("--limit doit être un entier >= 1.")
        population = population[:args.limit]

    answers = []
    with open(args.output, "w", encoding="utf-8") as out:
        for i, row in enumerate(population, 1):
            prompt = build_prompt(i, header, row, mapping, args.question)
            answer = " ".join(ask_ollama(prompt, args.model).split()).replace('"', "'")
            line = f'individu{i} : "{answer}"'
            out.write(line + "\n\n")  # fin de ligne + ligne vide entre chaque individu
            out.flush()
            answers.append(line)
            print(f"[{i}/{len(population)}] fait", file=sys.stderr)

    if len(answers) >= 5:
        print("\n".join(answers[:5]))
    else:
        print(f"La population contient moins de 5 personnes ({len(answers)}).", file=sys.stderr)


if __name__ == "__main__":
    main()