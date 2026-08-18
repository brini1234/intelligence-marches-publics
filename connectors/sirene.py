import os
from datetime import date, datetime
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.insee.fr/api-sirene/3.11"


def _headers():
    api_key = os.getenv("SIRENE_API_KEY")
    if not api_key:
        raise RuntimeError("SIRENE_API_KEY manquant dans le fichier .env")
    return {"X-INSEE-Api-Key-Integration": api_key}


def rechercher_entreprise_par_nom(nom: str, limite: int = 5) -> list[dict]:
    """
    Cherche une entreprise par sa dénomination.
    Retourne une liste de dicts simplifiés (siren, denomination, etat).
    """
    url = f"{BASE_URL}/siret"
    params = {
        "q": f'denominationUniteLegale:"{nom}"',
        "nombre": limite,
    }
    reponse = requests.get(url, headers=_headers(), params=params, timeout=10)
    reponse.raise_for_status()
    data = reponse.json()

    resultats = []
    for etab in data.get("etablissements", []):
        unite = etab.get("uniteLegale", {})
        resultats.append({
            "siren": etab.get("siren"),
            "siret": etab.get("siret"),
            "denomination": unite.get("denominationUniteLegale"),
            "etat_administratif": unite.get("etatAdministratifUniteLegale"),
            "est_siege": etab.get("etablissementSiege"),
        })
    return resultats


def rechercher_par_denomination_historique(nom: str, limite: int = 20) -> list[dict]:
    """
    Cherche dans l'HISTORIQUE des dénominations (périodes passées d'une
    unité légale), pas seulement la dénomination courante — opérateur
    periode() de l'API v3.11. Sert à retrouver un SIREN dont la dénomination
    a changé depuis (sujet, section 8 : piège "changement de raison
    sociale") : un rapprochement flou (niveau 3) contre le stock national
    échoue par construction dans ce cas, puisque ce stock ne porte que la
    dénomination courante.

    Vérifié en direct sur un cas réel : GET /siren?q=periode(denominationUniteLegale:"FRANCE TELECOM")
    retourne bien le SIREN 380129866 (dénomination "FRANCE TELECOM" jusqu'au
    2013-06-30, "ORANGE" depuis).

    La recherche de l'API est en texte libre (peut aussi remonter des
    dénominations proches mais différentes, ex. "FRANCE TELECOM CABLE") :
    filtrer par égalité exacte après normalisation incombe à l'appelant
    (scripts/agent_investigation_identite.py), pas à cette fonction.

    Retourne la liste brute des unités légales (avec leur periodesUniteLegale).
    """
    url = f"{BASE_URL}/siren"
    params = {
        "q": f'periode(denominationUniteLegale:"{nom}")',
        "nombre": limite,
    }
    reponse = requests.get(url, headers=_headers(), params=params, timeout=10)
    reponse.raise_for_status()
    data = reponse.json()
    return data.get("unitesLegales", [])


class AccesRestreintSirene(Exception):
    """
    Levée quand l'API renvoie 403 sur un SIREN précis : l'établissement est à
    diffusion restreinte (non-diffusible), pas un problème de quota. Distinct
    d'une erreur réseau/quota transitoire : inutile de retenter en boucle,
    ce refus est permanent pour ce SIREN.
    """


def recuperer_entreprise_par_siren(siren: str) -> dict | None:
    """Récupère le détail complet d'une entreprise à partir de son SIREN."""
    url = f"{BASE_URL}/siren/{siren}"
    reponse = requests.get(url, headers=_headers(), timeout=10)
    if reponse.status_code == 404:
        return None
    if reponse.status_code == 403:
        raise AccesRestreintSirene(siren)
    reponse.raise_for_status()
    return reponse.json()


def _convertir_date(valeur):
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, date):
        return valeur
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, str):
        texte = valeur.strip()
        if not texte:
            return None
        if len(texte) >= 10:
            texte = texte[:10]
        try:
            return date.fromisoformat(texte)
        except ValueError:
            return None
    return None


def normaliser_ligne_sirene(etablissement_row: dict, unite_legale_row: dict | None = None) -> dict:
    """Normalise un enregistrement SIRENE issu du stock INSEE pour l’enrichissement de entreprises."""
    unite = unite_legale_row or {}
    siren = etablissement_row.get("siren") or unite.get("siren")
    if not siren:
        return {}

    etat_administratif = unite.get("etatAdministratifUniteLegale") or unite.get("etat_administratif")
    est_active = etat_administratif == "A"

    adresse = " ".join(
        part for part in [
            etablissement_row.get("complementAdresseEtablissement"),
            etablissement_row.get("numeroVoieEtablissement"),
            etablissement_row.get("indiceRepetitionEtablissement"),
            etablissement_row.get("dernierNumeroVoieEtablissement"),
            etablissement_row.get("indiceRepetitionDernierNumeroVoieEtablissement"),
            etablissement_row.get("typeVoieEtablissement"),
            etablissement_row.get("libelleVoieEtablissement"),
        ] if part
    )

    return {
        "siren": siren,
        "siret": etablissement_row.get("siret"),
        "raison_sociale_legale": unite.get("denominationUniteLegale") or unite.get("nomUniteLegale") or unite.get("denomination") or None,
        "forme_juridique": unite.get("categorieJuridiqueUniteLegale") or unite.get("forme_juridique") or None,
        "code_naf": unite.get("activitePrincipaleUniteLegale") or unite.get("activitePrincipaleNAF25UniteLegale") or None,
        "date_creation": _convertir_date(etablissement_row.get("dateCreationEtablissement") or unite.get("dateCreationUniteLegale")),
        "etat_administratif": etat_administratif,
        "est_active": est_active,
        "est_siege": bool(etablissement_row.get("etablissementSiege")),
        "adresse": adresse or None,
        "code_postal": etablissement_row.get("codePostalEtablissement"),
        "commune": etablissement_row.get("libelleCommuneEtablissement") or etablissement_row.get("commune"),
    }


if __name__ == "__main__":
    # Test manuel rapide : à lancer avec `python connectors/sirene.py`
    resultats = rechercher_entreprise_par_nom("CAPGEMINI")
    for r in resultats:
        print(r)