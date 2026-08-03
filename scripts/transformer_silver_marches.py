"""
Transformation BRONZE -> SILVER (sujet, section 6, S2 : "déduplication").

Reconstruit intégralement silver_marches et silver_attributions (TRUNCATE +
repeuplement) depuis bronze_decp_marches / bronze_ted_notices.

Deux tables distinctes, pas une seule :
    - silver_marches      : un marché = une ligne (attributs acheteur,
      objet, montant, dates, CPV). Dédupliquée par uid, en gardant la
      version la plus récente (modification_id le plus élevé d'abord —
      c'est le sens de ce champ côté DECP —, puis date_chargement la plus
      récente en cas d'égalité).
    - silver_attributions  : un couple (marché, titulaire) = une ligne.
      **Un accord-cadre peut avoir plusieurs titulaires** (constaté en
      bronze : un même uid avec jusqu'à 9 titulaire_id différents pour le
      même modification_id) — les fusionner dans une seule ligne comme
      silver_marches ferait disparaître des concurrents réels, exactement
      ce que ce projet doit éviter. Dédupliquée par (uid, siret_titulaire)
      sur tout l'historique bronze ; seuls les SIRET valides à 14 chiffres
      sont retenus (jamais un identifiant inventé).

Détection de doublons inter-sources (limite documentée dans le README : un
même marché au-dessus des seuils UE peut apparaître à la fois dans DECP et
dans TED) : une ligne TED de silver_marches est flaguée doublon_probable_de
quand elle partage avec une ligne DECP le même siret_acheteur, un préfixe
CPV à 4 chiffres identique, un montant à moins de 1% et une date de
notification à moins de 30 jours. Jamais supprimée, seulement flaguée — la
ligne DECP est privilégiée comme référence (section 3 du sujet : DECP
publie le SIRET, "ce qui transforme une supposition en jointure exacte").

Usage :
    python scripts/transformer_silver_marches.py
"""
import sys

sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine


def transformer_silver_marches():
    engine = get_engine()

    with engine.begin() as connexion:
        print("Reconstruction de silver_marches / silver_attributions (TRUNCATE + repeuplement) ...")
        connexion.execute(text("TRUNCATE TABLE silver_attributions, silver_marches"))

        print("  silver_marches <- bronze_decp_marches (dernière version par uid) ...")
        connexion.execute(text(r"""
            INSERT INTO silver_marches (
                uid, source, siret_acheteur, nom_acheteur,
                objet, montant, code_cpv,
                date_notification, date_publication, duree_mois,
                duree_restante_mois, modification_id
            )
            SELECT DISTINCT ON (uid)
                uid,
                'DECP',
                CASE WHEN acheteur_id ~ '^\d{14}$' THEN acheteur_id ELSE NULL END,
                NULLIF(acheteur_nom, ''),
                NULLIF(objet, ''),
                NULLIF(montant, '')::numeric,
                NULLIF(code_cpv, ''),
                NULLIF(date_notification, '')::date,
                NULLIF(date_publication, '')::date,
                NULLIF(duree_mois, '')::numeric,
                NULLIF(duree_restante_mois, '')::numeric,
                COALESCE(NULLIF(modification_id, '')::int, 0)
            FROM bronze_decp_marches
            WHERE uid IS NOT NULL
            ORDER BY uid, COALESCE(NULLIF(modification_id, '')::int, 0) DESC, date_chargement DESC
        """))

        print("  silver_marches <- bronze_ted_notices (dernière version par avis) ...")
        connexion.execute(text(r"""
            INSERT INTO silver_marches (
                uid, source, siret_acheteur, nom_acheteur,
                objet, montant, code_cpv,
                date_notification, date_publication, duree_mois,
                duree_restante_mois, modification_id
            )
            SELECT DISTINCT ON (publication_number)
                'TED-' || publication_number,
                'TED',
                CASE WHEN buyer_identifier ~ '^\d{14}$' THEN buyer_identifier ELSE NULL END,
                NULLIF(buyer_name, ''),
                NULLIF(objet, ''),
                NULLIF(montant, '')::numeric,
                NULLIF(code_cpv, ''),
                NULLIF(publication_date, '')::date,
                NULLIF(publication_date, '')::date,
                NULL,
                NULL,
                NULL
            FROM bronze_ted_notices
            WHERE publication_number IS NOT NULL
            ORDER BY publication_number, date_chargement DESC
        """))

        print("  silver_attributions <- bronze_decp_marches (tous les titulaires distincts par marché) ...")
        connexion.execute(text(r"""
            INSERT INTO silver_attributions (uid, siret_titulaire, nom_titulaire, source)
            SELECT DISTINCT uid, titulaire_id, titulaire_nom, 'DECP'
            FROM bronze_decp_marches
            WHERE titulaire_id ~ '^\d{14}$'
              AND uid IN (SELECT uid FROM silver_marches WHERE source = 'DECP')
            ON CONFLICT (uid, siret_titulaire) DO NOTHING
        """))

        print("  silver_attributions <- bronze_ted_notices ...")
        connexion.execute(text(r"""
            INSERT INTO silver_attributions (uid, siret_titulaire, nom_titulaire, source)
            SELECT DISTINCT 'TED-' || publication_number, winner_identifier, winner_name, 'TED'
            FROM bronze_ted_notices
            WHERE winner_identifier ~ '^\d{14}$'
              AND ('TED-' || publication_number) IN (SELECT uid FROM silver_marches WHERE source = 'TED')
            ON CONFLICT (uid, siret_titulaire) DO NOTHING
        """))

        print("  Détection des doublons probables inter-sources (DECP/TED) ...")
        resultat_doublons = connexion.execute(text("""
            UPDATE silver_marches ted
            SET doublon_probable_de = decp.uid
            FROM silver_marches decp
            WHERE ted.source = 'TED'
              AND decp.source = 'DECP'
              AND ted.doublon_probable_de IS NULL
              AND ted.siret_acheteur IS NOT NULL
              AND ted.siret_acheteur = decp.siret_acheteur
              AND ted.code_cpv IS NOT NULL AND decp.code_cpv IS NOT NULL
              AND LEFT(ted.code_cpv, 4) = LEFT(decp.code_cpv, 4)
              AND ted.montant IS NOT NULL AND decp.montant IS NOT NULL
              AND ABS(ted.montant - decp.montant) <= 0.01 * GREATEST(decp.montant, 1)
              AND ted.date_notification IS NOT NULL AND decp.date_notification IS NOT NULL
              AND ABS(ted.date_notification - decp.date_notification) <= 30
        """))

        nb_total = connexion.execute(text("SELECT COUNT(*) FROM silver_marches")).scalar()
        nb_uid_distincts = connexion.execute(text("SELECT COUNT(DISTINCT uid) FROM silver_marches")).scalar()
        nb_decp = connexion.execute(text("SELECT COUNT(*) FROM silver_marches WHERE source = 'DECP'")).scalar()
        nb_ted = connexion.execute(text("SELECT COUNT(*) FROM silver_marches WHERE source = 'TED'")).scalar()
        nb_sans_acheteur = connexion.execute(text(
            "SELECT COUNT(*) FROM silver_marches WHERE siret_acheteur IS NULL"
        )).scalar()
        nb_attributions = connexion.execute(text("SELECT COUNT(*) FROM silver_attributions")).scalar()

    print(f"\n✅ Transformation silver terminée.")
    print(f"  silver_marches : {nb_total} ligne(s) ({nb_decp} DECP, {nb_ted} TED), "
          f"{nb_uid_distincts} uid distinct(s)")
    print(f"  silver_attributions : {nb_attributions} couple(s) marché/titulaire distinct(s)")
    print(f"  {resultat_doublons.rowcount} doublon(s) probable(s) inter-sources flagué(s) "
          f"(non supprimés, exclus de gold uniquement)")
    print(f"  {nb_sans_acheteur} marché(s) sans SIRET acheteur valide "
          f"(conservé(s) en silver pour audit, exclu(s) de gold)")


if __name__ == "__main__":
    transformer_silver_marches()
