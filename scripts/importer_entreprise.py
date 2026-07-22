import sys
sys.path.append(".")

from sqlalchemy import text
from connectors.sirene import rechercher_entreprise_par_nom
from db.connection import get_engine


def importer(nom_entreprise: str):
    engine = get_engine()
    resultats = rechercher_entreprise_par_nom(nom_entreprise)

    if not resultats:
        print(f"Aucune entreprise trouvée pour « {nom_entreprise} »")
        return

    # On traite les établissements sièges en premier, pour avoir le bon siret_siege dès le départ
    resultats_tries = sorted(resultats, key=lambda r: not r["est_siege"])

    with engine.begin() as connexion:
        for r in resultats_tries:
            if not r["siren"]:
                continue
            connexion.execute(text("""
                INSERT INTO entreprises (siren, siret_siege, denomination, est_active)
                VALUES (:siren, :siret, :denomination, :actif)
                ON CONFLICT (siren) DO UPDATE SET
                    siret_siege = COALESCE(entreprises.siret_siege, EXCLUDED.siret_siege),
                    denomination = EXCLUDED.denomination,
                    est_active = EXCLUDED.est_active
            """), {
                "siren": r["siren"],
                "siret": r["siret"] if r["est_siege"] else None,
                "denomination": r["denomination"],
                "actif": r["etat_administratif"] == "A",
            })
    print(f"{len(resultats)} établissement(s) traité(s) pour « {nom_entreprise} »")


if __name__ == "__main__":
    importer("CAPGEMINI")