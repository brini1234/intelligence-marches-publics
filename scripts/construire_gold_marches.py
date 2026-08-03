"""
Construction de la couche GOLD (tables métier) depuis silver_marches et
silver_attributions.

Remplace la logique qui peuplait auparavant directement les tables métier
depuis les tables de passage DECP/TED (scripts/charger_bronze_decp.py et
charger_bronze_ted.py ne font plus que charger bronze désormais). Ce script
lit exclusivement silver_marches (niveau marché) et silver_attributions
(niveau titulaire — un marché peut en avoir plusieurs, cf. commentaire dans
db/schema.sql), déjà dédupliquées et validées par
scripts/transformer_silver_marches.py.

Règle métier appliquée ici (pas en silver, qui garde tout pour l'audit) :
un marché doit avoir un SIRET acheteur valide pour exister dans `marches`
(la table le référence). Les lignes silver flaguées comme doublon probable
d'une autre source (doublon_probable_de IS NOT NULL) ne créent pas de ligne
`marches` séparée, pour ne pas compter deux fois le même marché dans les
futures métriques de concurrence (parties suivantes du sujet) — la ligne
silver reste néanmoins consultable pour audit.

Idempotent (ON CONFLICT DO NOTHING partout) : peut être relancé sans
risque après un TRUNCATE des tables métier, ou en complément d'un
chargement bronze/silver incrémental.

Usage :
    python scripts/construire_gold_marches.py
"""
import sys

sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine


def construire_gold_marches():
    engine = get_engine()

    with engine.begin() as connexion:
        print("Construction de la couche gold depuis silver_marches ...")

        # 1. Acheteurs
        connexion.execute(text("""
            INSERT INTO acheteurs (siret, nom)
            SELECT DISTINCT ON (siret_acheteur)
                siret_acheteur, COALESCE(nom_acheteur, 'Acheteur inconnu')
            FROM silver_marches
            WHERE siret_acheteur IS NOT NULL
              AND doublon_probable_de IS NULL
            ORDER BY siret_acheteur
            ON CONFLICT (siret) DO NOTHING
        """))

        # 2. Marchés (source et modification_id viennent de silver ; les
        # doublons probables inter-sources sont exclus ici)
        connexion.execute(text("""
            INSERT INTO marches (
                uid, siret_acheteur, objet, montant, duree_mois,
                duree_restante_mois, code_cpv,
                date_notification, date_publication, modification_id,
                donnees_actuelles, source
            )
            SELECT
                uid, siret_acheteur, objet, montant, duree_mois,
                duree_restante_mois, code_cpv,
                date_notification, date_publication,
                COALESCE(modification_id, 0), TRUE, source
            FROM silver_marches
            WHERE siret_acheteur IS NOT NULL
              AND doublon_probable_de IS NULL
            ON CONFLICT (uid) DO NOTHING
        """))

        # 3. Entreprises titulaires (jamais un SIREN inventé : uniquement
        # les lignes où silver a validé un SIRET titulaire à 14 chiffres).
        # Un marché flagué doublon ou sans acheteur valide n'a pas de ligne
        # `marches` (étape 2) : ses titulaires n'ont donc rien à référencer
        # et sont exclus ici aussi (jointure sur silver_marches).
        connexion.execute(text("""
            INSERT INTO entreprises (siren, denomination, est_active)
            SELECT DISTINCT ON (siren) siren, denomination, TRUE
            FROM (
                SELECT LEFT(sa.siret_titulaire, 9) AS siren,
                       COALESCE(sa.nom_titulaire, 'Inconnu') AS denomination
                FROM silver_attributions sa
                JOIN silver_marches sm ON sm.uid = sa.uid
                WHERE sm.siret_acheteur IS NOT NULL
                  AND sm.doublon_probable_de IS NULL
            ) t
            ORDER BY siren
            ON CONFLICT (siren) DO NOTHING
        """))

        # 4. Attributions (relie marché et titulaire — plusieurs titulaires
        # possibles par marché, cf. silver_attributions). methode_resolution/
        # score_confiance propagés depuis silver : les parties suivantes
        # (fiche de faits) doivent pouvoir signaler le doute d'une
        # résolution floue, pas la traiter comme aussi certaine qu'un SIRET
        # exact (sujet section 8 : "résolution correcte OU DOUTE SIGNALÉ").
        connexion.execute(text("""
            INSERT INTO attributions (uid_marche, siret_titulaire, siren_titulaire, methode_resolution, score_confiance)
            SELECT DISTINCT sa.uid, sa.siret_titulaire, LEFT(sa.siret_titulaire, 9),
                   sa.methode_resolution, sa.score_confiance
            FROM silver_attributions sa
            JOIN silver_marches sm ON sm.uid = sa.uid
            WHERE sm.siret_acheteur IS NOT NULL
              AND sm.doublon_probable_de IS NULL
            ON CONFLICT (uid_marche, siret_titulaire) DO NOTHING
        """))

        nb_acheteurs = connexion.execute(text("SELECT COUNT(*) FROM acheteurs")).scalar()
        nb_marches = connexion.execute(text("SELECT COUNT(*) FROM marches")).scalar()
        nb_entreprises = connexion.execute(text("SELECT COUNT(*) FROM entreprises")).scalar()
        nb_attributions = connexion.execute(text("SELECT COUNT(*) FROM attributions")).scalar()
        nb_exclus_sans_acheteur = connexion.execute(text(
            "SELECT COUNT(*) FROM silver_marches WHERE siret_acheteur IS NULL"
        )).scalar()
        nb_exclus_doublons = connexion.execute(text(
            "SELECT COUNT(*) FROM silver_marches WHERE doublon_probable_de IS NOT NULL"
        )).scalar()
        repartition_methode = connexion.execute(text(
            "SELECT methode_resolution, COUNT(*) FROM attributions GROUP BY 1 ORDER BY 2 DESC"
        )).fetchall()

    print(f"\n✅ Construction gold terminée. Totaux en base : "
          f"{nb_acheteurs:,} acheteurs, {nb_marches:,} marchés, "
          f"{nb_entreprises:,} entreprises, {nb_attributions:,} attributions".replace(",", " "))
    print(f"  Exclus de gold : {nb_exclus_sans_acheteur} sans SIRET acheteur valide, "
          f"{nb_exclus_doublons} doublon(s) probable(s) inter-sources "
          f"(visibles en silver_marches pour audit)")
    print(f"  Méthode de résolution des attributions : {dict(repartition_methode)}")


if __name__ == "__main__":
    construire_gold_marches()
