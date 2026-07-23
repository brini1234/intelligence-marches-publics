import sys
sys.path.append(".")
from scripts.detecter_sortant import detecter_sortant


def test_detecter_sortant_renvoie_une_structure_coherente():
    resultat = detecter_sortant("21750001600019", "45441000")
    assert "sortant_probable" in resultat
    assert "confiance" in resultat
    assert resultat["confiance"] in ["aucune", "faible", "moyenne", "élevée"]