import sys
sys.path.append(".")

from scripts.detecter_sortant import detecter_sortant

# Correspondance entre le niveau de confiance textuel (Partie 3) et un score numérique de couverture
SCORES_COUVERTURE = {
    "élevée": 1.0,
    "moyenne": 0.66,
    "faible": 0.33,
    "aucune": 0.0,
}


def construire_fiche_de_faits(siret_acheteur: str, code_cpv: str) -> dict:
    """
    Transforme un résultat de détection du sortant en fiche de faits JSON.
    Chaque fait porte sa valeur, sa provenance, et son score de couverture.
    Aucune donnée ici ne peut être inventée : tout vient de detecter_sortant(),
    qui lui-même ne lit que la base PostgreSQL.
    """
    resultat = detecter_sortant(siret_acheteur, code_cpv)
    score = SCORES_COUVERTURE.get(resultat["confiance"], 0.0)

    if resultat["sortant_probable"] is None:
        return {
            "faits": [],
            "couverture_globale": 0.0,
            "raison": resultat["raison"],
        }

    fiche = {
        "faits": [
            {
                "cle": "titulaire_actuel",
                "valeur": resultat["sortant_probable"],
                "provenance": "table entreprises, via jointure attributions/marches",
                "couverture": score,
            },
            {
                "cle": "duree_restante_mois",
                "valeur": resultat["duree_restante_mois"],
                "provenance": "table marches, champ duree_restante_mois (source DECP)",
                "couverture": score,
            },
            {
                "cle": "date_dernier_marche",
                "valeur": resultat["date_notification"],
                "provenance": "table marches, champ date_notification",
                "couverture": score,
            },
            {
                "cle": "nombre_marches_historique",
                "valeur": resultat["nb_marches_famille"],
                "provenance": "COUNT sur marches filtré par acheteur et code_cpv",
                "couverture": score,
            },
        ],
        "couverture_globale": score,
        "marches_support": resultat["marches_support"],
    }
    return fiche


if __name__ == "__main__":
    import json
    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    print(json.dumps(fiche, indent=2, ensure_ascii=False, default=str))