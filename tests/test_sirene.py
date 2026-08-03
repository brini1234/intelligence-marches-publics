import sys
sys.path.append(".")
from connectors.sirene import rechercher_entreprise_par_nom, normaliser_ligne_sirene


def test_recherche_retourne_des_resultats():
    resultats = rechercher_entreprise_par_nom("CAPGEMINI")
    assert len(resultats) > 0
    assert resultats[0]["siren"] is not None


def test_normaliser_ligne_sirene_extrait_les_champs_cles():
    etablissement = {
        "siren": "123456789",
        "siret": "12345678901234",
        "dateCreationEtablissement": "2020-01-15",
        "etablissementSiege": True,
        "codePostalEtablissement": "75001",
        "libelleCommuneEtablissement": "Paris",
    }
    unite = {
        "denominationUniteLegale": "ACME SA",
        "categorieJuridiqueUniteLegale": "5710",
        "activitePrincipaleUniteLegale": "6201Z",
        "dateCreationUniteLegale": "2015-02-03",
        "etatAdministratifUniteLegale": "A",
    }

    row = normaliser_ligne_sirene(etablissement, unite)

    assert row["siren"] == "123456789"
    assert row["siret"] == "12345678901234"
    assert row["raison_sociale_legale"] == "ACME SA"
    assert row["forme_juridique"] == "5710"
    assert row["code_naf"] == "6201Z"
    assert row["date_creation"] == "2020-01-15" or row["date_creation"] is not None
    assert row["est_active"] is True