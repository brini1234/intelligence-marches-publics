import sys
sys.path.append(".")

from sqlalchemy import text
from db.connection import get_engine


def detecter_sortant(siret_acheteur: str, code_cpv: str) -> dict:
    """
    Pour un acheteur et un code CPV donnés, identifie le titulaire probable
    actuel (le "sortant") et estime sa date d'expiration.

    Logique :
    - On regarde tous les marchés du même acheteur, avec le même code CPV
      (une "famille" de marchés, ex: tous les marchés d'électricité).
    - Le marché le plus récent (date_notification la plus tardive) désigne
      le sortant probable.
    - Le niveau de confiance dépend du nombre de marchés observés dans
      cette famille (plus il y a d'historique, plus la confiance est haute).
    """
    engine = get_engine()

    with engine.connect() as connexion:
        resultats = connexion.execute(text("""
            SELECT
                m.uid,
                m.objet,
                m.montant,
                m.date_notification,
                m.duree_mois,
                m.duree_restante_mois,
                a.siren_titulaire,
                e.denomination
            FROM marches m
            JOIN attributions a ON a.uid_marche = m.uid
            JOIN entreprises e ON e.siren = a.siren_titulaire
            WHERE m.siret_acheteur = :siret_acheteur
              AND m.code_cpv = :code_cpv
            ORDER BY m.date_notification DESC
        """), {
            "siret_acheteur": siret_acheteur,
            "code_cpv": code_cpv,
        }).mappings().all()

    if not resultats:
        return {
            "sortant_probable": None,
            "confiance": "aucune",
            "raison": "Aucun marché trouvé pour cet acheteur et ce CPV",
            "marches_support": [],
        }

    marche_actuel = resultats[0]
    nb_marches_famille = len(resultats)

    # Niveau de confiance : basé sur la quantité d'historique observé
    if nb_marches_famille >= 3:
        confiance = "élevée"
    elif nb_marches_famille == 2:
        confiance = "moyenne"
    else:
        confiance = "faible"

    return {
        "sortant_probable": marche_actuel["denomination"],
        "siren_sortant": marche_actuel["siren_titulaire"],
        "date_notification": str(marche_actuel["date_notification"]),
        "duree_restante_mois": marche_actuel["duree_restante_mois"],
        "confiance": confiance,
        "nb_marches_famille": nb_marches_famille,
        "raison": f"{nb_marches_famille} marché(s) observé(s) pour cet acheteur sur ce CPV",
        "marches_support": [r["uid"] for r in resultats],
    }


if __name__ == "__main__":
    import json
    # Exemple : Cour des Comptes, CPV 72220000 (conseil en systèmes informatiques)
    resultat = detecter_sortant("11000028800016", "72220000")
    print(json.dumps(resultat, indent=2, ensure_ascii=False, default=str))