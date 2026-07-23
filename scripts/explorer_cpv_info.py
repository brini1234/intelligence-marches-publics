import requests
import json

RESOURCE_ID = "22847056-61df-452d-837d-8b8ceadbfc52"
BASE_URL = f"https://tabular-api.data.gouv.fr/api/resources/{RESOURCE_ID}/data/"


def chercher_marches_informatiques(limite: int = 10):
    """
    Cherche des marchés dont le code CPV commence par 72 (services informatiques),
    pour trouver un acheteur pertinent pour le périmètre du sujet.
    """
    params = {
        "codeCPV__contains": "72",
        "page_size": limite,
    }
    reponse = requests.get(BASE_URL, params=params, timeout=15)
    reponse.raise_for_status()
    data = reponse.json()

    print(f"Total de marchés CPV 72xxxxxx trouvés : {data['meta']['total']}")
    print("---")
    for m in data["data"]:
        print(f"Acheteur: {m.get('acheteur_nom')} (SIRET: {m.get('acheteur_id')}) "
              f"| CPV: {m.get('codeCPV')} | Objet: {m.get('objet', '')[:60]}")


if __name__ == "__main__":
    chercher_marches_informatiques()