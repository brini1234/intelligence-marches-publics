import requests

RESOURCE_ID = "22847056-61df-452d-837d-8b8ceadbfc52"
BASE_URL = f"https://tabular-api.data.gouv.fr/api/resources/{RESOURCE_ID}/data/"


def rechercher_marches_par_acheteur(siret_acheteur: str, limite: int = 50) -> list[dict]:
    """
    Récupère les marchés attribués par un acheteur public donné (identifié par son SIRET).
    Ne garde que les données actuelles (donneesActuelles = true) pour éviter les doublons d'avenants.
    """
    params = {
        "acheteur_id__exact": siret_acheteur,
        "donneesActuelles__exact": "true",
        "page_size": limite,
    }
    reponse = requests.get(BASE_URL, params=params, timeout=15)
    reponse.raise_for_status()
    data = reponse.json()
    return data.get("data", [])


if __name__ == "__main__":
    marches = rechercher_marches_par_acheteur("43276694700019")
    print(f"{len(marches)} marché(s) récupéré(s)")
    for m in marches[:3]:
        print(m)