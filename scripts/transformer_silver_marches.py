"""
Transformation BRONZE -> SILVER (sujet, section 6, S2 : "déduplication" ;
section 5 : hiérarchie de résolution d'identité).

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
from scripts.resolution_identite import resoudre


def _resoudre_acheteurs_niveaux_2_3(connexion) -> int:
    """
    Niveaux 2/3 de la hiérarchie de résolution d'identité (sujet section 5),
    appliqués aux acheteurs dont l'identifiant brut a échoué au niveau 1
    (siret_acheteur encore NULL en silver_marches à ce stade). Ne touche
    jamais une ligne déjà résolue au niveau 1.
    """
    lignes = connexion.execute(text(r"""
        SELECT uid, acheteur_id AS identifiant_brut, acheteur_nom AS nom_brut
        FROM bronze_decp_marches
        WHERE acheteur_id IS NOT NULL AND acheteur_id !~ '^\d{14}$'
          AND uid IN (SELECT uid FROM silver_marches WHERE source = 'DECP' AND siret_acheteur IS NULL)
        UNION
        SELECT 'TED-' || publication_number, buyer_identifier, buyer_name
        FROM bronze_ted_notices
        WHERE buyer_identifier IS NOT NULL AND buyer_identifier !~ '^\d{14}$'
          AND ('TED-' || publication_number) IN (
              SELECT uid FROM silver_marches WHERE source = 'TED' AND siret_acheteur IS NULL
          )
    """)).fetchall()

    nb_resolus = 0
    for uid, identifiant_brut, nom_brut in lignes:
        resultats = resoudre(identifiant_brut, nom_brut, connexion)
        if not resultats:
            continue
        r = resultats[0]  # un seul acheteur par marché : premier résultat retenu
        resultat_maj = connexion.execute(text("""
            UPDATE silver_marches
            SET siret_acheteur = :siret, nom_acheteur = COALESCE(nom_acheteur, :nom),
                methode_resolution_acheteur = :methode, score_confiance_acheteur = :score
            WHERE uid = :uid AND siret_acheteur IS NULL
        """), {
            "siret": r["siret"], "nom": nom_brut, "methode": r["methode"],
            "score": r.get("score_confiance"), "uid": uid,
        })
        nb_resolus += resultat_maj.rowcount
    return nb_resolus


def _resoudre_titulaires_niveaux_2_3(connexion) -> int:
    """Même principe que ci-dessus, côté titulaires. Un identifiant brut
    peut produire plusieurs résultats (champ multi-valeurs : co-traitance
    concaténée dans une seule chaîne) -> plusieurs lignes silver_attributions."""
    lignes = connexion.execute(text(r"""
        SELECT DISTINCT uid, titulaire_id AS identifiant_brut, titulaire_nom AS nom_brut, 'DECP' AS source
        FROM bronze_decp_marches
        WHERE titulaire_id IS NOT NULL AND titulaire_id !~ '^\d{14}$'
          AND titulaire_nom IS NOT NULL AND titulaire_nom <> ''
          AND uid IN (SELECT uid FROM silver_marches WHERE source = 'DECP')
        UNION
        SELECT DISTINCT 'TED-' || publication_number, winner_identifier, winner_name, 'TED'
        FROM bronze_ted_notices
        WHERE winner_identifier IS NOT NULL AND winner_identifier !~ '^\d{14}$'
          AND winner_name IS NOT NULL
          AND ('TED-' || publication_number) IN (SELECT uid FROM silver_marches WHERE source = 'TED')
    """)).fetchall()

    nb_resolus = 0
    for uid, identifiant_brut, nom_brut, source in lignes:
        for r in resoudre(identifiant_brut, nom_brut, connexion):
            resultat = connexion.execute(text("""
                INSERT INTO silver_attributions (uid, siret_titulaire, nom_titulaire, source, methode_resolution, score_confiance)
                VALUES (:uid, :siret, :nom, :source, :methode, :score)
                ON CONFLICT (uid, siret_titulaire) DO NOTHING
            """), {
                "uid": uid, "siret": r["siret"], "nom": nom_brut, "source": source,
                "methode": r["methode"], "score": r.get("score_confiance"),
            })
            nb_resolus += resultat.rowcount
    return nb_resolus


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

        print("  Résolution d'identité niveaux 2/3 (acheteurs) — normalisation puis rapprochement flou ...")
        nb_acheteurs_resolus = _resoudre_acheteurs_niveaux_2_3(connexion)
        print(f"    {nb_acheteurs_resolus} acheteur(s) supplémentaire(s) résolu(s)")

        print("  Résolution d'identité niveaux 2/3 (titulaires) — normalisation puis rapprochement flou ...")
        nb_titulaires_resolus = _resoudre_titulaires_niveaux_2_3(connexion)
        print(f"    {nb_titulaires_resolus} couple(s) marché/titulaire supplémentaire(s) résolu(s)")

        # Validation de plausibilité des dates (sujet, section 6 : silver
        # "validée"). Une erreur de saisie côté source peut produire une
        # date syntaxiquement valide mais absurde (ex. constaté en base :
        # '0206-06-23') : ::date l'accepte silencieusement, contrairement
        # au SIRET déjà validé par regex. Bornes larges (pas un jugement sur
        # la fenaître de 3-5 ans du périmètre, seulement un filtre anti-
        # corruption) : jamais une date fabriquée en remplacement, seulement
        # NULL — même principe que le reste de la couche silver.
        print("  Validation de plausibilité des dates (bornes 2000-01-01 .. aujourd'hui+2 ans) ...")
        resultat_dates_notif = connexion.execute(text("""
            UPDATE silver_marches
            SET date_notification = NULL
            WHERE date_notification IS NOT NULL
              AND date_notification NOT BETWEEN DATE '2000-01-01' AND (CURRENT_DATE + INTERVAL '2 years')::date
        """))
        resultat_dates_publi = connexion.execute(text("""
            UPDATE silver_marches
            SET date_publication = NULL
            WHERE date_publication IS NOT NULL
              AND date_publication NOT BETWEEN DATE '2000-01-01' AND (CURRENT_DATE + INTERVAL '2 years')::date
        """))
        nb_dates_invalidees = resultat_dates_notif.rowcount + resultat_dates_publi.rowcount

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
        repartition_methode_acheteur = connexion.execute(text("""
            SELECT COALESCE(methode_resolution_acheteur, 'siret_exact'), COUNT(*)
            FROM silver_marches WHERE siret_acheteur IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC
        """)).fetchall()
        repartition_methode_titulaire = connexion.execute(text("""
            SELECT methode_resolution, COUNT(*) FROM silver_attributions GROUP BY 1 ORDER BY 2 DESC
        """)).fetchall()

    print(f"\n✅ Transformation silver terminée.")
    print(f"  silver_marches : {nb_total} ligne(s) ({nb_decp} DECP, {nb_ted} TED), "
          f"{nb_uid_distincts} uid distinct(s)")
    print(f"  silver_attributions : {nb_attributions} couple(s) marché/titulaire distinct(s)")
    print(f"  {resultat_doublons.rowcount} doublon(s) probable(s) inter-sources flagué(s) "
          f"(non supprimés, exclus de gold uniquement)")
    print(f"  {nb_dates_invalidees} date(s) implausible(s) détectée(s) et mise(s) à NULL "
          f"(hors 2000-01-01 .. aujourd'hui+2 ans, jamais une date fabriquée en remplacement)")
    print(f"  {nb_sans_acheteur} marché(s) toujours sans SIRET acheteur valide "
          f"(conservé(s) en silver pour audit, exclu(s) de gold)")
    print(f"  Méthode de résolution acheteurs : {dict(repartition_methode_acheteur)}")
    print(f"  Méthode de résolution titulaires : {dict(repartition_methode_titulaire)}")


if __name__ == "__main__":
    transformer_silver_marches()
