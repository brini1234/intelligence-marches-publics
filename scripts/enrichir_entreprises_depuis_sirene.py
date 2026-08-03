"""
Enrichit `entreprises` (table métier, liée aux marchés publics) à partir du
référentiel national SIRENE désormais chargé en base par
importer_stock_sirene_national.py.

Contrairement à l'ancienne version (connectors/sirene_stock.py +
scripts/importer_stock_sirene.py, qui filtrait via DuckDB avant de charger),
cette étape est maintenant une simple jointure SQL : les deux tables sont
déjà dans PostgreSQL, donc un UPDATE ... FROM suffit. Deux instructions SQL
en tout, aucune boucle Python, appliquées à TOUTES les lignes de
`entreprises` en une seule passe.

Prérequis : avoir lancé scripts/importer_stock_sirene_national.py avant.

Usage :
    python scripts/enrichir_entreprises_depuis_sirene.py
"""
import sys
sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine


def enrichir_entreprises_depuis_sirene():
    engine = get_engine()

    with engine.begin() as connexion:
        nb_avant = connexion.execute(text(
            "SELECT COUNT(*) FROM entreprises WHERE code_naf IS NOT NULL"
        )).scalar()

        # 1. Dénomination, forme juridique, NAF, date de création, état administratif
        connexion.execute(text("""
            UPDATE entreprises e
            SET raison_sociale_legale = NULLIF(ul."denominationUniteLegale", ''),
                denomination = CASE
                    WHEN e.denomination IS NULL OR e.denomination = 'Inconnu'
                    THEN COALESCE(NULLIF(ul."denominationUniteLegale", ''), e.denomination)
                    ELSE e.denomination
                END,
                forme_juridique = NULLIF(ul."categorieJuridiqueUniteLegale", ''),
                code_naf = NULLIF(ul."activitePrincipaleUniteLegale", ''),
                date_creation = NULLIF(ul."dateCreationUniteLegale", '')::date,
                etat_administratif = NULLIF(ul."etatAdministratifUniteLegale", ''),
                est_active = (ul."etatAdministratifUniteLegale" = 'A')
            FROM sirene_stock_unite_legale ul
            WHERE ul.siren = e.siren
        """))

        # 2. Adresse et établissement siège (uniquement la ligne où etablissementSiege = 'true')
        connexion.execute(text("""
            UPDATE entreprises e
            SET siret_siege = et.siret,
                est_siege = true,
                adresse = NULLIF(TRIM(CONCAT_WS(' ',
                    NULLIF(et."numeroVoieEtablissement", ''),
                    NULLIF(et."typeVoieEtablissement", ''),
                    NULLIF(et."libelleVoieEtablissement", '')
                )), ''),
                code_postal = NULLIF(et."codePostalEtablissement", ''),
                commune = NULLIF(et."libelleCommuneEtablissement", '')
            FROM sirene_stock_etablissement et
            WHERE et.siren = e.siren
              AND et."etablissementSiege" = 'true'
        """))

        nb_total = connexion.execute(text("SELECT COUNT(*) FROM entreprises")).scalar()
        nb_apres = connexion.execute(text(
            "SELECT COUNT(*) FROM entreprises WHERE code_naf IS NOT NULL"
        )).scalar()
        nb_denomination_connue = connexion.execute(text(
            "SELECT COUNT(*) FROM entreprises WHERE denomination IS NOT NULL AND denomination <> 'Inconnu'"
        )).scalar()
        nb_introuvables = connexion.execute(text("""
            SELECT COUNT(*) FROM entreprises e
            WHERE NOT EXISTS (SELECT 1 FROM sirene_stock_unite_legale ul WHERE ul.siren = e.siren)
        """)).scalar()

    print(f"Entreprises en base                : {nb_total}")
    print(f"  code NAF renseigné avant/après    : {nb_avant} -> {nb_apres} ({nb_apres / nb_total:.0%})")
    print(f"  dénomination légale connue        : {nb_denomination_connue} ({nb_denomination_connue / nb_total:.0%})")
    print(f"  introuvables dans SIRENE national  : {nb_introuvables} "
          f"(SIREN invalide, ou entreprise radiée avant l'historique disponible)")


if __name__ == "__main__":
    enrichir_entreprises_depuis_sirene()
