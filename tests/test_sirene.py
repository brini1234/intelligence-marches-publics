import sys
sys.path.append(".")
from connectors.sirene import rechercher_entreprise_par_nom


def test_recherche_retourne_des_resultats():
    resultats = rechercher_entreprise_par_nom("CAPGEMINI")
    assert len(resultats) > 0
    assert resultats[0]["siren"] is not None