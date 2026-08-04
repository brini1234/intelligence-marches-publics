import sys
sys.path.append(".")
from scripts.marches_similaires import trouver_marches_similaires


def test_erreur_si_ni_uid_ni_texte():
    try:
        trouver_marches_similaires()
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_erreur_si_uid_et_texte():
    try:
        trouver_marches_similaires(uid="x", texte="y")
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_marches_similaires_par_texte_retourne_un_score():
    resultats = trouver_marches_similaires(texte="conseil en systèmes informatiques", limite=5)
    assert len(resultats) > 0
    for r in resultats:
        assert 0.0 <= r["similarite"] <= 1.0
        assert r["uid"] is not None
