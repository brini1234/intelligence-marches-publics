import sys
sys.path.append(".")

from scripts.detecter_sortant import detecter_sortant

SCORES_COUVERTURE = {
    "élevée": 1.0,
    "moyenne": 0.66,
    "faible": 0.33,
    "aucune": 0.0,
}


def construire_fiche_de_faits(siret_acheteur: str, code_cpv: str) -> dict:
    """
    Transforme un résultat de détection du sortant en fiche de faits JSON,
    conforme au bloc de décision exigé : sortant, concurrents, fourchette de
    prix, pondération de l'acheteur (non couverte), couverture globale.
    """
    resultat = detecter_sortant(siret_acheteur, code_cpv)
    score = SCORES_COUVERTURE.get(resultat["confiance"], 0.0)

    if resultat["sortant_probable"] is None:
        return {
            "faits": [],
            "couverture_globale": 0.0,
            "raison": resultat["raison"],
        }

    historique = resultat["historique"]

    # Concurrents observés : les autres entreprises de la même famille de marchés,
    # hors le sortant actuel, sans doublon, dans l'ordre d'apparition
    concurrents = []
    for h in historique[1:]:
        if h["denomination"] not in concurrents and h["denomination"] != resultat["sortant_probable"]:
            concurrents.append(h["denomination"])

    # Fourchette de prix observée sur toute la famille de marchés
    montants = [h["montant"] for h in historique if h["montant"] is not None]
    prix_min = min(montants) if montants else None
    prix_max = max(montants) if montants else None

    faits = [
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
        {
            "cle": "concurrents_observes",
            "valeur": concurrents if concurrents else "aucun autre concurrent observé",
            "provenance": "table attributions, entreprises distinctes hors sortant sur la même famille CPV",
            # Couverture réduite si un seul marché observé au total (pas de vrai historique concurrentiel)
            "couverture": score if resultat["nb_marches_famille"] > 1 else 0.0,
        },
        {
            "cle": "fourchette_prix_min",
            "valeur": prix_min,
            "provenance": "MIN(montant) sur marches de la même famille",
            "couverture": score,
        },
        {
            "cle": "fourchette_prix_max",
            "valeur": prix_max,
            "provenance": "MAX(montant) sur marches de la même famille",
            "couverture": score,
        },
        {
            "cle": "ponderation_acheteur",
            "valeur": "non disponible",
            "provenance": "aucune source connectée ne publie les critères de pondération prix/technique",
            "couverture": 0.0,
        },
    ]

    # Couverture globale : moyenne des couvertures de tous les faits (honnête, pas juste le meilleur cas)
    couverture_globale = sum(f["couverture"] for f in faits) / len(faits)

    return {
        "faits": faits,
        "couverture_globale": round(couverture_globale, 2),
        "marches_support": resultat["marches_support"],
    }


if __name__ == "__main__":
    import json
    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    print(json.dumps(fiche, indent=2, ensure_ascii=False, default=str))