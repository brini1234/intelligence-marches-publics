"""
Peuple `etablissements` avec l'adresse exacte de chaque SIRET qui a
effectivement remporté un marché public (attributions.siret_titulaire).

Différence avec l'enrichissement déjà fait sur `entreprises` : ce dernier ne
capture que l'établissement SIÈGE de chaque entreprise. Mais le SIRET qui
signe un marché n'est pas toujours le siège (filiale, agence régionale...).
Sans cette étape, l'adresse affichée pour un titulaire pourrait être celle du
siège social alors que c'est une autre implantation qui a réellement le
marché — trompeur pour l'analyse concurrentielle géographique.

Le périmètre est déduit automatiquement des SIRET déjà présents dans
`attributions` (donc du périmètre marchés publics IT), pas d'une sélection
manuelle. Jointure SQL unique contre le référentiel national déjà chargé.

Usage :
    python scripts/enrichir_etablissements_depuis_sirene.py
"""
import sys
sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine


def enrichir_etablissements_depuis_sirene():
    engine = get_engine()

    with engine.begin() as connexion:
        nb_sirets_a_couvrir = connexion.execute(text(
            "SELECT COUNT(DISTINCT siret_titulaire) FROM attributions WHERE siret_titulaire IS NOT NULL"
        )).scalar()

        # INSERT ... ON CONFLICT : idempotent, relançable sans risque de doublon.
        connexion.execute(text("""
            INSERT INTO etablissements (siret, siren, est_siege, adresse, code_postal, commune)
            SELECT DISTINCT
                a.siret_titulaire,
                et.siren,
                (et."etablissementSiege" = 'true'),
                NULLIF(TRIM(CONCAT_WS(' ',
                    NULLIF(et."numeroVoieEtablissement", ''),
                    NULLIF(et."typeVoieEtablissement", ''),
                    NULLIF(et."libelleVoieEtablissement", '')
                )), ''),
                NULLIF(et."codePostalEtablissement", ''),
                NULLIF(et."libelleCommuneEtablissement", '')
            FROM attributions a
            JOIN sirene_stock_etablissement et ON et.siret = a.siret_titulaire
            WHERE a.siret_titulaire IS NOT NULL
            ON CONFLICT (siret) DO UPDATE SET
                siren = EXCLUDED.siren,
                est_siege = EXCLUDED.est_siege,
                adresse = EXCLUDED.adresse,
                code_postal = EXCLUDED.code_postal,
                commune = EXCLUDED.commune,
                date_maj = NOW()
        """))

        nb_couverts = connexion.execute(text("SELECT COUNT(*) FROM etablissements")).scalar()
        nb_introuvables = connexion.execute(text("""
            SELECT COUNT(DISTINCT a.siret_titulaire)
            FROM attributions a
            WHERE a.siret_titulaire IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM etablissements e WHERE e.siret = a.siret_titulaire)
        """)).scalar()

    print(f"SIRET titulaires distincts à couvrir : {nb_sirets_a_couvrir}")
    print(f"Établissements renseignés            : {nb_couverts} ({nb_couverts / nb_sirets_a_couvrir:.0%})")
    print(f"Introuvables dans le stock national   : {nb_introuvables} "
          f"(établissement fermé/radié avant l'historique, ou SIRET mal saisi dans DECP)")


if __name__ == "__main__":
    enrichir_etablissements_depuis_sirene()
