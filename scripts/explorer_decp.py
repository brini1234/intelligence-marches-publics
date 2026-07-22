import requests
import json

RESOURCE_ID = "22847056-61df-452d-837d-8b8ceadbfc52"
BASE_URL = f"https://tabular-api.data.gouv.fr/api/resources/{RESOURCE_ID}/data/"


def explorer(siret_acheteur: str, limite: int = 1):
    params = {
        "acheteur_id__exact": siret_acheteur,
        "page_size": limite,
    }
    reponse = requests.get(BASE_URL, params=params, timeout=15)
    reponse.raise_for_status()
    data = reponse.json()

    print(f"Total de marchés trouvés : {data['meta']['total']}")
    print("---")
    if data["data"]:
        print(json.dumps(data["data"][0], indent=2, ensure_ascii=False))
    else:
        print("Aucun résultat pour ce SIRET.")


if __name__ == "__main__":
    # SIRET de test : Région Bretagne (acheteur public actif et volumineux)
    explorer("43276694700019")