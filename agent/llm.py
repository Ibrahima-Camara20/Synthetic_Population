"""
Accès au modèle de langage
==========================

Trois façons d'appeler un LLM, choisies avec --backend :

  openai     toute API compatible OpenAI : OpenAI, Mistral, Groq, LM Studio,
             et Ollama en local (base_url http://localhost:11434/v1, pas de clé)
  anthropic  l'API Claude d'Anthropic
  ollama     Ollama en local, via son API native (réflexion des modèles Qwen3
             désactivée par défaut : beaucoup plus rapide)
  test       aucun modèle : des répliques construites à partir des fiches,
             pour tester toute la chaîne sans clé ni connexion

La clé se met dans la variable d'environnement LLM_API_KEY (ou OPENAI_API_KEY /
ANTHROPIC_API_KEY). Aucune bibliothèque externe n'est nécessaire.
"""

import json
import os
import re
import urllib.request


class ErreurLLM(RuntimeError):
    pass


def _post(url, entetes, corps, delai=600):
    req = urllib.request.Request(url, data=json.dumps(corps).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **entetes})
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ErreurLLM(f"{e.code} {e.reason} : {e.read().decode('utf-8', 'replace')[:500]}")
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise ErreurLLM(f"le modèle n'a pas répondu en {delai // 60} minutes : "
                            "essayez --sans-reflexion ou --tours 6")
        raise ErreurLLM(f"connexion impossible à {url} : {e.reason}")
    except TimeoutError:
        raise ErreurLLM(f"le modèle n'a pas répondu en {delai // 60} minutes : "
                        "essayez --sans-reflexion ou --tours 6")


class ClientLLM:
    def __init__(self, backend="openai", modele=None, base_url=None, temperature=0.9,
                 max_tokens=200, sans_reflexion=False):
        self.backend = backend
        self.modele = modele
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.sans_reflexion = sans_reflexion
        if backend == "openai":
            self.base_url = (base_url or os.environ.get("LLM_BASE_URL")
                             or "https://api.openai.com/v1").rstrip("/")
            self.cle = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
            if not modele:
                raise ErreurLLM("indiquez --modele (ex. gpt-4o-mini, mistral-small-latest, llama3.1)")
        elif backend == "anthropic":
            self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
            self.cle = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or ""
            if not self.cle:
                raise ErreurLLM("clé manquante : définissez ANTHROPIC_API_KEY")
            if not modele:
                raise ErreurLLM("indiquez --modele (ex. claude-sonnet-5-5)")
        elif backend == "ollama":
            self.base_url = (base_url or "http://localhost:11434").rstrip("/")
            if self.base_url.endswith("/v1"):
                self.base_url = self.base_url[:-3]
            if not modele:
                raise ErreurLLM("indiquez --modele (le nom exact affiché par « ollama list »)")
        elif backend != "test":
            raise ErreurLLM(f"backend inconnu : {backend}")

    def repondre(self, systeme, messages):
        """systeme : consigne du rôle ; messages : [{'role': 'user'|'assistant', 'content': ...}]"""
        if self.backend == "openai":
            entetes = {"Authorization": f"Bearer {self.cle}"} if self.cle else {}
            if self.sans_reflexion:
                systeme += "\n/no_think"        # interrupteur reconnu par les modèles Qwen3
            corps = {"model": self.modele, "temperature": self.temperature,
                     "max_tokens": self.max_tokens,
                     "messages": [{"role": "system", "content": systeme}] + messages}
            if self.sans_reflexion and ":11434" in self.base_url:
                corps["think"] = False           # option d'Ollama, ignorée si non reconnue
            r = _post(f"{self.base_url}/chat/completions", entetes, corps)
            contenu = r["choices"][0]["message"].get("content") or ""
            # Modèles qui « réfléchissent » (Qwen3, DeepSeek-R1…) : on retire la réflexion
            contenu = re.sub(r"<think>.*?(</think>|$)", "", contenu, flags=re.S).strip()
            if not contenu:
                raise ErreurLLM("réponse vide : le modèle a sans doute utilisé toute la limite de "
                                "longueur pour réfléchir. Relancez avec --max-tokens 1500.")
            return contenu
        if self.backend == "anthropic":
            entetes = {"x-api-key": self.cle, "anthropic-version": "2023-06-01"}
            corps = {"model": self.modele, "temperature": self.temperature,
                     "max_tokens": self.max_tokens, "system": systeme, "messages": messages}
            r = _post(f"{self.base_url}/messages", entetes, corps)
            return "".join(b.get("text", "") for b in r["content"])
        if self.backend == "ollama":
            corps = {"model": self.modele, "stream": False,
                     "think": False,              # pas de réflexion : réponse directe
                     "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
                     "messages": [{"role": "system", "content": systeme}] + messages}
            try:
                r = _post(f"{self.base_url}/api/chat", {}, corps)
            except ErreurLLM as e:
                if "think" in str(e).lower():     # modèle sans mode réflexion : on retire l'option
                    corps.pop("think")
                    r = _post(f"{self.base_url}/api/chat", {}, corps)
                else:
                    raise
            contenu = re.sub(r"<think>.*?(</think>|$)", "", r["message"].get("content") or "",
                             flags=re.S).strip()
            if not contenu:
                raise ErreurLLM("réponse vide du modèle : relancez avec --max-tokens 1500")
            return contenu
        raise ErreurLLM("le backend 'test' est géré par le moteur de scène")