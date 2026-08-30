"""
Connecteur "web ouvert" (sujet, section 3 : "Web ouvert | Sans garantie |
Faible | Enrichissement uniquement"). Aucune API de recherche web générique
gratuite et stable n'existe pour ce genre d'usage ponctuel et à faible
volume : ce connecteur interroge l'interface HTML publique de DuckDuckGo
(html.duckduckgo.com/html/), sans clé, comme le ferait un navigateur.

Fragile par nature (page HTML non versionnée, pas une API contractuelle) —
exactement ce que la fiabilité "Sans garantie" du sujet annonce. Utilisé
uniquement par scripts/agent_enrichissement_web.py, en dernier recours,
avec dégradation gracieuse systématique : toute erreur (réseau, timeout,
changement de structure HTML) renvoie une liste vide, jamais une exception
qui remonterait jusqu'au briefing.
"""
import re

import requests

URL_RECHERCHE = "https://html.duckduckgo.com/html/"
EN_TETES = {"User-Agent": "Mozilla/5.0 (compatible; stage-intelligence-marches-publics/1.0)"}

# Un résultat DuckDuckGo (page HTML) : un lien titré (result__a) suivi de son
# extrait (result__snippet). Format non documenté, susceptible de changer —
# c'est précisément pour ça que ce connecteur dégrade gracieusement sur tout
# échec de correspondance, plutôt que de supposer qu'il matchera toujours.
REGEX_RESULTAT = re.compile(
    r'class="result__a"[^>]*>(?P<titre>.*?)</a>.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
)
REGEX_BALISE = re.compile(r"<[^>]+>")


def _nettoyer_html(texte: str) -> str:
    texte = REGEX_BALISE.sub("", texte)
    return (
        texte.replace("&#x27;", "'").replace("&amp;", "&")
        .replace("&quot;", '"').strip()
    )


def rechercher_web(requete: str, max_resultats: int = 10, timeout: int = 8) -> list[str]:
    """
    Recherche texte libre sur le web ouvert. Retourne une liste de chaînes
    "titre — extrait" (jusqu'à max_resultats), ou [] sur tout échec —
    jamais d'exception : c'est la garantie de dégradation gracieuse exigée
    par le sujet pour cet agent.
    """
    try:
        reponse = requests.get(
            URL_RECHERCHE, params={"q": requete}, headers=EN_TETES, timeout=timeout,
        )
        reponse.raise_for_status()
    except Exception:
        return []

    resultats = []
    for m in REGEX_RESULTAT.finditer(reponse.text):
        titre = _nettoyer_html(m.group("titre"))
        snippet = _nettoyer_html(m.group("snippet"))
        resultats.append(f"{titre} — {snippet}")
        if len(resultats) >= max_resultats:
            break
    return resultats


if __name__ == "__main__":
    # Test manuel rapide : à lancer avec `python connectors/web_ouvert.py`
    for r in rechercher_web("CAPGEMINI SIREN"):
        print(r)
