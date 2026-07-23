import sys
sys.path.append(".")

from sqlalchemy import text
from connectors.decp import rechercher_marches_par_acheteur
from db.connection import get_engine


def importer(siret_acheteur: str):
    engine = get_engine()
    marches = rechercher_marches_par_acheteur(siret_acheteur)

    if not marches:
        print(f"Aucun marché trouvé pour l'acheteur {siret_acheteur}")
        return

    with engine.begin() as connexion:
        # 1. S'assurer que l'acheteur existe
        nom_acheteur = marches[0].get("acheteur_nom", "Acheteur inconnu")
        connexion.execute(text("""
            INSERT INTO acheteurs (siret, nom)
            VALUES (:siret, :nom)
            ON CONFLICT (siret) DO NOTHING
        """), {"siret": siret_acheteur, "nom": nom_acheteur})

        # 2. Insérer chaque marché
        for m in marches:
            connexion.execute(text("""
                INSERT INTO marches (
                    uid, id_marche, siret_acheteur, objet, montant,
                    duree_mois, duree_restante_mois, code_cpv,
                    date_notification, date_publication,
                    modification_id, donnees_actuelles
                )
                VALUES (
                    :uid, :id_marche, :siret_acheteur, :objet, :montant,
                    :duree_mois, :duree_restante_mois, :code_cpv,
                    :date_notification, :date_publication,
                    :modification_id, :donnees_actuelles
                )
                ON CONFLICT (uid) DO NOTHING
            """), {
                "uid": m.get("uid"),
                "id_marche": m.get("id"),
                "siret_acheteur": siret_acheteur,
                "objet": m.get("objet"),
                "montant": m.get("montant"),
                "duree_mois": m.get("dureeMois"),
                "duree_restante_mois": m.get("dureeRestanteMois"),
                "code_cpv": m.get("codeCPV"),
                "date_notification": m.get("dateNotification"),
                "date_publication": m.get("datePublicationDonnees"),
                "modification_id": m.get("modification_id", 0),
                "donnees_actuelles": m.get("donneesActuelles", True),
            })

            # 3. Relier le(s) titulaire(s), en créant l'entreprise si besoin
            siret_titulaire = m.get("titulaire_id")
            if siret_titulaire and len(siret_titulaire) == 14:
                siren_titulaire = siret_titulaire[:9]
                connexion.execute(text("""
                    INSERT INTO entreprises (siren, denomination, est_active)
                    VALUES (:siren, :denomination, TRUE)
                    ON CONFLICT (siren) DO NOTHING
                """), {
                    "siren": siren_titulaire,
                    "denomination": m.get("titulaire_nom") or "Inconnu",
                })
                connexion.execute(text("""
                    INSERT INTO attributions (uid_marche, siret_titulaire, siren_titulaire)
                    VALUES (:uid_marche, :siret_titulaire, :siren_titulaire)
                    ON CONFLICT (uid_marche, siret_titulaire) DO NOTHING
                """), {
                    "uid_marche": m.get("uid"),
                    "siret_titulaire": siret_titulaire,
                    "siren_titulaire": siren_titulaire,
                })

    print(f"{len(marches)} marché(s) traité(s) pour l'acheteur {siret_acheteur}")


if __name__ == "__main__":
    importer("43276694700019")