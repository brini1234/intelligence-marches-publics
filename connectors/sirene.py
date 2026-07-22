import os
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


def recuperer_entreprise_par_siren(siren: str) -> dict | None:
    """Récupère le détail complet d'une entreprise à partir de son SIREN."""
    url = f"{BASE_URL}/siren/{siren}"
    reponse = requests.get(url, headers=_headers(), timeout=10)
    if reponse.status_code == 404:
        return None
    reponse.raise_for_status()
    return reponse.json()


if __name__ == "__main__":
    # Test manuel rapide : à lancer avec `python connectors/sirene.py`
    resultats = rechercher_entreprise_par_nom("CAPGEMINI")
    for r in resultats:
        print(r)