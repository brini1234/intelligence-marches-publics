"""
Connecteur TED (Tenders Electronic Daily) — API Search publique v3, sans clé.

Vérifié en conditions réelles le 2026-08-03 (comme le préconise le sujet S1,
"explorer TED à la main") contre https://api.ted.europa.eu/v3/notices/search :
    - POST, corps JSON {"query": ..., "fields": [...], "scope": "ACTIVE",
      "paginationMode": "ITERATION"}, anonyme (aucune clé requise).
    - Champs eForms (kebab-case) confirmés utiles pour ce périmètre :
      notice-type, form-type (form-type="result" = avis d'attribution),
      publication-number, publication-date, buyer-name, buyer-country,
      buyer-identifier, winner-name, winner-country, winner-identifier,
      classification-cpv, total-value, notice-title, procedure-type.
    - buyer-identifier / winner-identifier renvoient, pour les entités
      françaises, un identifiant à 14 chiffres au format SIRET (ex.
      "93843503900012") — une vraie jointure est possible, pas seulement un
      nom. Absent sur une partie des avis (cf. limite déjà documentée pour
      DECP : jamais un SIRET inventé si absent).
    - Pagination par itérationNextToken (pas de page numérotée).
    - Pour "services informatiques (CPV 72xxxxxx), France, 3 ans" (périmètre
      du sujet, section 6) : ~330 avis d'attribution au 2026-08-03. Volume
      largement gérable par une insertion SQL directe, contrairement à DECP
      (millions de lignes) qui justifie DuckDB + COPY.
"""
import os
from datetime import date, timedelta

import requests

BASE_URL = "https://api.ted.europa.eu/v3/notices/search"

CHAMPS = [
    "publication-number", "notice-identifier", "notice-type", "form-type",
    "publication-date", "dispatch-date",
    "buyer-name", "buyer-country", "buyer-identifier",
    "winner-name", "winner-country", "winner-identifier",
    "classification-cpv", "total-value", "notice-title",
    "procedure-type",
]

TAILLE_PAGE = 250


def _valeur_ou_premier_element(valeur):
    """buyer-name/winner-name rendent une liste par langue (["NOM"]) ;
    notice-title rend une chaîne directe par langue. On gère les deux."""
    if isinstance(valeur, list):
        return valeur[0] if valeur else None
    return valeur


def _premiere_valeur_multilingue(champ) -> str | None:
    """
    Les champs texte TED (buyer-name, winner-name, notice-title...) sont
    rendus par langue : {"fra": [...] ou "...", "eng": [...] ou "...", ...}.
    On préfère le français quand il existe, sinon la première langue
    disponible.
    """
    if not champ:
        return None
    if isinstance(champ, str):
        return champ
    if "fra" in champ and champ["fra"]:
        return _valeur_ou_premier_element(champ["fra"])
    for valeurs in champ.values():
        resultat = _valeur_ou_premier_element(valeurs)
        if resultat:
            return resultat
    return None


def _premiere_date(valeur: str | None) -> str | None:
    """Les dates TED sont au format ISO avec fuseau ("2026-04-28+02:00" ou
    "2026-04-27Z") : les 10 premiers caractères suffisent pour une DATE SQL."""
    if not valeur or len(valeur) < 10:
        return None
    return valeur[:10]


def _rechercher_page(query: str, iteration_token: str | None = None) -> dict:
    corps = {
        "query": query,
        "fields": CHAMPS,
        "limit": TAILLE_PAGE,
        "scope": "ACTIVE",
        "paginationMode": "ITERATION",
    }
    if iteration_token:
        corps["iterationNextToken"] = iteration_token
    reponse = requests.post(BASE_URL, json=corps, timeout=30)
    reponse.raise_for_status()
    return reponse.json()


def _code_cpv_du_perimetre(identifiants_cpv: list[str], prefixe_cpv: str | None) -> str | None:
    """
    Un avis TED porte souvent plusieurs codes CPV (classification-cpv est une
    liste). Quand la requête filtre sur "au moins un code commence par
    prefixe_cpv" (prefixe_cpv non None), le premier élément de la liste
    n'est pas forcément celui qui a fait matcher le filtre — le stocker tel
    quel pouvait silencieusement placer un marché hors périmètre 72xxxxxx
    dans `marches.code_cpv` (bug trouvé en vérifiant la base : 45/273
    marchés TED concernés). On préfère donc le code qui appartient
    réellement au périmètre demandé ; à défaut, on retombe sur le premier
    élément plutôt que de perdre le CPV.

    prefixe_cpv=None (défaut depuis le 31/08/2026, cf. exporter_perimetre_complet
    ci-dessous) : aucun filtre de périmètre n'est appliqué à la requête —
    on retient simplement le premier code CPV de la liste, représentatif,
    sans supposer d'appartenance à un périmètre particulier.
    """
    if not identifiants_cpv:
        return None
    if prefixe_cpv is None:
        return identifiants_cpv[0]
    return next((c for c in identifiants_cpv if c.startswith(prefixe_cpv)), identifiants_cpv[0])


def _normaliser_notice(brute: dict, prefixe_cpv: str) -> dict:
    identifiants_cpv = brute.get("classification-cpv") or []
    return {
        "publication_number": brute.get("publication-number"),
        "notice_identifier": brute.get("notice-identifier"),
        "publication_date": _premiere_date(brute.get("publication-date")),
        "buyer_name": _premiere_valeur_multilingue(brute.get("buyer-name")) or "Acheteur inconnu",
        "buyer_country": (brute.get("buyer-country") or [None])[0],
        "buyer_identifier": (brute.get("buyer-identifier") or [None])[0],
        "winner_name": _premiere_valeur_multilingue(brute.get("winner-name")),
        "winner_country": (brute.get("winner-country") or [None])[0],
        "winner_identifier": (brute.get("winner-identifier") or [None])[0],
        "code_cpv": _code_cpv_du_perimetre(identifiants_cpv, prefixe_cpv),
        "montant": brute.get("total-value"),
        "objet": _premiere_valeur_multilingue(brute.get("notice-title")),
        "procedure_type": brute.get("procedure-type"),
    }


def exporter_perimetre_complet(
    prefixe_cpv: str | None = None,
    pays: str = "FRA",
    annees_historique: int = 3,
) -> list[dict]:
    """
    Récupère l'intégralité des avis d'attribution (form-type=result) France/
    3 ans — tous secteurs, tous acheteurs, aucune sélection manuelle — via
    pagination complète par itérationNextToken jusqu'à épuisement des
    résultats.

    prefixe_cpv=None (défaut depuis le 31/08/2026) : aucun filtre CPV à la
    requête — ~7 900 avis (contre ~330 avec l'ancien filtre CPV 72xxxxxx en
    dur). Même raisonnement que connectors/decp.py : filtrer par CPV à la
    source écarterait définitivement tout marché mal étiqueté. Le périmètre
    CPV 72xxxxxx du sujet (section 6) est appliqué en aval, dans
    scripts/construire_gold_marches.py. Passer prefixe_cpv="72" reste
    possible pour un export ponctuel restreint (ancien comportement).
    """
    date_min = date.today() - timedelta(days=365 * annees_historique)
    query = f"buyer-country={pays} AND publication-date>={date_min:%Y%m%d} AND form-type=result"
    if prefixe_cpv:
        query = f"classification-cpv={prefixe_cpv}* AND {query}"

    notices: list[dict] = []
    token = None
    while True:
        page = _rechercher_page(query, iteration_token=token)
        lot = page.get("notices", [])
        notices_normalisees = (_normaliser_notice(n, prefixe_cpv) for n in lot)
        # Le filtre buyer-country de la requête n'est pas fiable côté API :
        # constaté en base (bronze_ted_notices), des institutions UE hors
        # France (Commission européenne à Bruxelles/BEL, Parlement européen
        # à Luxembourg/LUX) sont renvoyées malgré buyer-country=FRA. Même
        # principe que _code_cpv_du_perimetre : ne jamais faire confiance
        # au seul filtre de requête, revérifier sur la valeur réellement
        # portée par chaque notice avant de la garder.
        notices.extend(n for n in notices_normalisees if n["buyer_country"] == pays)
        token = page.get("iterationNextToken")
        total = page.get("totalNoticeCount", 0)
        if not lot or not token or len(notices) >= total:
            break

    return notices


if __name__ == "__main__":
    # Test manuel rapide : à lancer avec `python connectors/ted.py`
    resultats = exporter_perimetre_complet()
    print(f"{len(resultats)} avis d'attribution récupéré(s)")
    for r in resultats[:3]:
        print(r)
