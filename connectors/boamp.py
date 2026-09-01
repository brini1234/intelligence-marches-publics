"""
Connecteur BOAMP (Bulletin officiel des annonces de marchés publics), open
data DILA. Sujet, section 3 : "BOAMP | France, avis | Moyenne | Recoupement
et détection" ; section 6 (S1) : "Explorer TED, DECP et BOAMP à la main."

Rôle documenté par le sujet, jamais dévié ici : BOAMP sert au recoupement et
à la détection (scripts/detecter_recoupement_boamp.py), jamais de source
d'identité comme DECP/TED/SIRENE. Vérifié en conditions réelles le
31/08/2026 sur plusieurs avis d'attribution réels : ni le champ TITULAIRE ni
le champ IDENTITE (acheteur) du bloc "donnees" ne portent de SIRET, quelle
que soit l'année — seuls DENOMINATION/ADRESSE sont disponibles. Aucune
jointure exacte n'est donc possible depuis cette source, seulement un
rapprochement approximatif (nom normalisé, CPV, date, éventuellement
montant) — cohérent avec la fiabilité "Moyenne" du sujet, à la différence de
DECP (SIRET publié, section 3 : "transforme une supposition en jointure
exacte").

Exploration menée le 31/08/2026 (sujet, S1) contre l'API opendatasoft de
data.economie.gouv.fr (DILA), deux générations d'API coexistent :
    - v1 (/api/records/1.0/search/) : filtre catégoriel `refine.*`
      fonctionnel, mais AUCUNE syntaxe de requête sur intervalle de dates
      qui fonctionne (`q=champ:[... TO ...]` renvoie systématiquement 400,
      quel que soit le format de date essayé) — inutilisable pour ce
      périmètre (fenêtre de 3 ans).
    - v2.1 (/api/explore/v2.1/catalog/datasets/boamp/records) : langage
      ODSQL (`where=...`), comparaisons de date fonctionnelles
      (`dateparution >= "2023-01-01"`), mais `nature_categorise_libelle`
      n'accepte pas une égalité stricte (`= "Résultat de marché"` renvoie 0
      résultat alors que le facet correspondant existe et compte 464 545
      avis) — nécessite `startswith(nature_categorise_libelle, "Résultat de
      marché")`, jamais supposé sans vérification. `limit` plafonné à 100
      par page (pagination par `offset`) ; ET `offset + limit <= 10 000`
      (erreur `InvalidRESTParameterError`, vérifié en conditions réelles :
      un fetch complet sur ~136 000 avis heurte ce plafond après une
      centaine de pages) — inutilisable seul pour une récupération complète
      au-delà de 10 000 lignes.
    - `/api/explore/v2.1/catalog/datasets/boamp/exports/json` : mêmes
      paramètres `where`, mais renvoie le résultat complet en un seul flux
      JSON (pas de pagination, pas de plafond `offset+limit` constaté) —
      c'est cet endpoint qu'utilise `rechercher_resultats_marche()` pour
      une récupération complète (`max_pages=None`) ; l'endpoint `records`
      paginé reste utilisé pour une exploration bornée (`max_pages` donné),
      plus rapide pour un test ou un échantillon.
    - Le CPV n'est PAS un facet interrogeable côté API, dans aucune des
      deux générations : niché dans le champ "donnees" (le JSON brut de
      l'avis, encodé en chaîne), sous OBJET.CPV.PRINCIPAL. Forme variable
      selon le marché — un dict {"PRINCIPAL": "..."} pour un marché
      mono-lot, une LISTE de dicts pour un marché multi-lots (un CPV par
      lot) — vérifié en direct sur des avis réels, jamais supposé. Filtrage
      CPV donc entièrement côté client, après récupération : même principe
      que connectors/ted.py::_code_cpv_du_perimetre (ne jamais faire
      confiance à un filtre serveur non vérifiable pour ce champ).
"""
import json
import time
from datetime import date, timedelta

import requests

BASE_URL_RECORDS = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
BASE_URL_EXPORT = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/exports/json"
TAILLE_PAGE = 100  # maximum accepté par l'API v2.1 pour /records (vérifié : 101 -> 400 Bad Request)
NB_ESSAIS_MAX = 5  # panne réseau transitoire constatée en conditions réelles (31/08/2026,
# "Network is unreachable" après 76 pages sur une pagination complète de ~1360) : sans
# retry, un seul aléa réseau mi-parcours perdait toute la progression déjà récupérée.


def _requete_avec_retry(url: str, params: dict, timeout: int):
    """GET avec retry/backoff exponentiel (1s, 2s, 4s, 8s, 16s) sur toute
    erreur réseau ou HTTP — panne transitoire constatée en conditions
    réelles (31/08/2026). Lève RuntimeError après épuisement des essais,
    jamais un plantage sans contexte (offset/url perdus)."""
    derniere_erreur = None
    for essai in range(NB_ESSAIS_MAX):
        try:
            reponse = requests.get(url, params=params, timeout=timeout)
            reponse.raise_for_status()
            return reponse
        except requests.exceptions.RequestException as e:
            derniere_erreur = e
            if essai < NB_ESSAIS_MAX - 1:
                time.sleep(2 ** essai)
    raise RuntimeError(
        f"BOAMP : échec réseau persistant après {NB_ESSAIS_MAX} essais ({url}, params={params})"
    ) from derniere_erreur


def _codes_cpv(donnees: dict) -> list[str]:
    """
    Normalise OBJET.CPV — dict ou liste de dicts selon que le marché est
    mono-lot ou multi-lots (forme vérifiée en conditions réelles, jamais
    supposée) — en liste de codes CPV (chaîne). Liste vide si absent.
    """
    objet = donnees.get("OBJET")
    if not isinstance(objet, dict):
        return []
    cpv = objet.get("CPV")
    if cpv is None:
        return []
    entrees = cpv if isinstance(cpv, list) else [cpv]
    return [e["PRINCIPAL"] for e in entrees if isinstance(e, dict) and e.get("PRINCIPAL")]


def _normaliser_enregistrement(champs: dict) -> dict | None:
    """Retourne None si le champ "donnees" est absent ou n'est pas un JSON
    exploitable — dégradation gracieuse, jamais une exception qui
    interromprait toute la pagination pour un seul avis malformé."""
    brut = champs.get("donnees")
    if not brut:
        return None
    try:
        donnees = json.loads(brut)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(donnees, dict):
        return None

    return {
        "idweb": champs.get("idweb"),
        "nomacheteur": champs.get("nomacheteur"),
        "titulaire": champs.get("titulaire"),
        "objet": champs.get("objet"),
        "date_parution": champs.get("dateparution"),
        "code_departement": (champs.get("code_departement") or [None])[0]
        if isinstance(champs.get("code_departement"), list) else champs.get("code_departement"),
        "codes_cpv": _codes_cpv(donnees),
    }


def rechercher_resultats_marche(
    prefixe_cpv: str | None = "72",
    annees_historique: int = 3,
    max_pages: int | None = None,
) -> list[dict]:
    """
    Récupère les avis "Résultat de marché" (attribution — le pendant BOAMP
    de form-type=result côté TED) sur la fenêtre demandée, pagination
    complète (offset/limit) jusqu'à épuisement, filtrage CPV entièrement
    côté client (cf. docstring module) après récupération.

    prefixe_cpv="72" (défaut) : ne retient que les avis dont au moins un
    code CPV commence par ce préfixe — périmètre du sujet (section 6).
    Passer prefixe_cpv=None retourne l'intégralité des avis d'attribution
    France, tous secteurs, sur la fenêtre demandée (utile pour une
    exploration ponctuelle, pas le périmètre par défaut de ce projet).

    max_pages : borne le nombre de pages récupérées via l'endpoint paginé
    `/records` (exploration rapide, tests — cf. docstring module : ce
    endpoint plafonne à `offset+limit <= 10 000`, donc adapté seulement à
    un échantillon). None (défaut) récupère l'intégralité du volume
    disponible via l'endpoint `/exports/json`, qui n'a pas ce plafond.
    """
    date_min = date.today() - timedelta(days=365 * annees_historique)
    where = f'startswith(nature_categorise_libelle, "Résultat de marché") AND dateparution >= "{date_min:%Y-%m-%d}"'

    if max_pages is not None:
        return _rechercher_par_pages(where, prefixe_cpv, max_pages)
    return _rechercher_export_complet(where, prefixe_cpv)


def _filtrer_et_normaliser(lignes: list[dict], prefixe_cpv: str | None) -> list[dict]:
    resultats = []
    for champs in lignes:
        normalise = _normaliser_enregistrement(champs)
        if normalise is None:
            continue
        if prefixe_cpv and not any(c.startswith(prefixe_cpv) for c in normalise["codes_cpv"]):
            continue
        resultats.append(normalise)
    return resultats


def _rechercher_par_pages(where: str, prefixe_cpv: str | None, max_pages: int) -> list[dict]:
    """Endpoint `/records`, pagination offset/limit — utilisé seulement pour
    un échantillon borné (max_pages), jamais pour une récupération complète
    (plafond offset+limit<=10000, cf. docstring module)."""
    resultats: list[dict] = []
    offset = 0
    page = 0
    while page < max_pages:
        reponse = _requete_avec_retry(
            BASE_URL_RECORDS, {"limit": TAILLE_PAGE, "offset": offset, "where": where}, timeout=30,
        )
        page_json = reponse.json()
        lignes = page_json.get("results", [])
        if not lignes:
            break
        resultats.extend(_filtrer_et_normaliser(lignes, prefixe_cpv))
        offset += TAILLE_PAGE
        page += 1
        if offset >= page_json.get("total_count", 0):
            break
    return resultats


def _rechercher_export_complet(where: str, prefixe_cpv: str | None) -> list[dict]:
    """Endpoint `/exports/json` — un seul flux JSON couvrant l'intégralité
    du résultat, sans plafond de pagination (vérifié en conditions réelles
    le 31/08/2026, cf. docstring module). Requête volumineuse (~136 000
    avis nationaux, plusieurs dizaines de Mo) : timeout large et retry
    inclus (_requete_avec_retry)."""
    reponse = _requete_avec_retry(BASE_URL_EXPORT, {"where": where}, timeout=300)
    lignes = reponse.json()
    return _filtrer_et_normaliser(lignes, prefixe_cpv)


if __name__ == "__main__":
    # Test manuel rapide : à lancer avec `python connectors/boamp.py`
    resultats = rechercher_resultats_marche(max_pages=3)
    print(f"{len(resultats)} avis d'attribution CPV72xxxxxx récupéré(s) (3 pages max, test rapide)")
    for r in resultats[:5]:
        print(r)
