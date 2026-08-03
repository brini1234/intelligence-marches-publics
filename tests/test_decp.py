import sys
sys.path.append(".")
from connectors.decp import rechercher_marches_par_acheteur


def test_recherche_retourne_des_marches():
    marches = rechercher_marches_par_acheteur("43276694700019")
    assert len(marches) > 0
    assert marches[0].get("uid") is not None
