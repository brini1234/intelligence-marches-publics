"""
Agent "Enrichissement web" (sujet, section 4) — troisième et dernier agent
prévu par le sujet, explicitement optionnel ("si le temps le permet").
Sujet, section 3 : "Web ouvert | Sans garantie | Faible | Enrichissement
uniquement" — jamais une source de vérité, seulement un indice à recouper.

Rôle retenu ici : dernier recours (niveau 5) de la hiérarchie de résolution
d'identité (scripts/resolution_identite.py, section 5 du sujet), quand le
rapprochement flou (niveau 3) et l'investigation SIRENE (niveau 4, continuité
+ historique de dénomination) ont tous deux échoué ou restent ambigus.
S'applique typiquement aux cas d'homonymie non résoluble autrement (ex.
"SMILE", "BELHARRA" : cf. README, limite assumée) — une recherche web peut
apporter le contexte (adresse, secteur) qu'aucune des données structurées
n'a fourni.

Mécanisme, conçu pour ne jamais fabriquer un résultat :
    1. recherche le nom sur le web ouvert (connectors/web_ouvert.py, sans
       clé, dégradation gracieuse déjà assurée à ce niveau) ;
    2. extrait les mentions de SIREN dans les résultats (annuaires publics :
       societe.com, pappers.fr, annuaire-entreprises.data.gouv.fr, etc.
       mentionnent presque toujours le SIREN en clair) ;
    3. ne retient un candidat QUE s'il apparaît sur au moins 2 résultats
       distincts — une mention isolée est trop fragile (page erronée, nom
       proche mais différent) pour servir de signal ;
    4. revérifie ce candidat contre le référentiel SIRENE national : jamais
       de confiance aveugle dans le contenu d'une page tierce, le SIREN doit
       réellement exister avec une dénomination correspondant au nom
       cherché (après normalisation).
Si une seule de ces conditions échoue : retourne None, jamais un pick
arbitraire — même principe que le reste de la hiérarchie de résolution.

Score de confiance volontairement le plus bas de toute la hiérarchie (0.4,
contre 0.55+ pour le rapprochement flou, 0.75 pour la continuité, 0.8 pour
l'historique SIRENE) : reflète la fiabilité "Faible" du web ouvert affichée
par le sujet (section 3), jamais traité comme une source de rang égal aux
sources officielles.
"""
import re
import sys
from collections import Counter

sys.path.append(".")

from sqlalchemy import text

from connectors.web_ouvert import rechercher_web
from scripts.resolution_identite import normaliser_nom, resoudre_siren_vers_siret_siege

# SIREN mentionné en clair dans un résultat de recherche : 9 chiffres,
# éventuellement séparés par des espaces ou points (format d'affichage
# habituel des annuaires d'entreprises, ex. "SIREN 508 008 984").
REGEX_SIREN_DANS_TEXTE = re.compile(r"\b(\d{3}[ .]?\d{3}[ .]?\d{3})\b")

SCORE_CONFIANCE_ENRICHISSEMENT_WEB = 0.4


def _sirens_mentionnes(texte: str) -> list[str]:
    return [m.group(1).replace(" ", "").replace(".", "") for m in REGEX_SIREN_DANS_TEXTE.finditer(texte)]


def enrichir_identite_via_web(nom_brut: str, connexion) -> dict | None:
    """
    Point d'entrée de l'agent. Retourne {"siret", "siren", "methode",
    "score_confiance"} si un candidat unique est corroboré par au moins 2
    résultats de recherche ET confirmé par le référentiel SIRENE, sinon
    None (dégradation gracieuse : le briefing reste valide sans ce
    candidat, simplement moins riche — exigence du sujet, section 4).
    """
    nom_normalise = normaliser_nom(nom_brut)
    if not nom_normalise:
        return None

    resultats = rechercher_web(f'"{nom_brut}" SIREN')
    if not resultats:
        return None

    comptage = Counter(siren for texte in resultats for siren in _sirens_mentionnes(texte))
    candidats_corrobores = [siren for siren, n in comptage.items() if n >= 2]
    if len(candidats_corrobores) != 1:
        return None  # aucun consensus (0 ou plusieurs candidats concurrents) -> doute signalé

    siren_candidat = candidats_corrobores[0]

    ligne = connexion.execute(text("""
        SELECT "denominationUniteLegale" FROM sirene_stock_unite_legale WHERE siren = :siren
    """), {"siren": siren_candidat}).fetchone()
    if ligne is None or normaliser_nom(ligne[0] or "") != nom_normalise:
        return None  # le web mentionne ce SIREN, mais SIRENE ne le confirme pas -> pas de confiance

    siret = resoudre_siren_vers_siret_siege(siren_candidat, connexion)
    if siret is None:
        return None

    return {
        "siret": siret, "siren": siren_candidat,
        "methode": "enrichissement_web", "score_confiance": SCORE_CONFIANCE_ENRICHISSEMENT_WEB,
    }


if __name__ == "__main__":
    # Test manuel rapide : à lancer avec `python scripts/agent_enrichissement_web.py`
    from db.connection import get_engine
    engine = get_engine()
    with engine.connect() as c:
        print(enrichir_identite_via_web("GEXPERTISE", c))
