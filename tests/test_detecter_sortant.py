import sys
sys.path.append(".")
from scripts.detecter_sortant import detecter_sortant


def test_detecter_sortant_renvoie_une_structure_coherente():
    resultat = detecter_sortant("11000028800016", "72220000")
    assert "sortant_probable" in resultat
    assert "confiance" in resultat
    assert resultat["confiance"] in ["aucune", "faible", "moyenne", "élevée"]


def test_detecter_sortant_gere_absence_de_donnees():
    resultat = detecter_sortant("00000000000000", "99999999")
    assert resultat["sortant_probable"] is None
    assert resultat["confiance"] == "aucune"    