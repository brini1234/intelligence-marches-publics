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


def test_detecter_sortant_deterministe_sur_accord_cadre_multi_titulaires():
    # Régression (bug trouvé par revue de code indépendante le 20/08/2026) :
    # quand le marché le plus récent est un accord-cadre à plusieurs
    # titulaires notifié en une seule fois, plusieurs lignes sont à égalité
    # sur date_notification -- sans tie-break explicite dans l'ORDER BY, le
    # sortant retourné dépendait du plan d'exécution PostgreSQL (non
    # garanti par le SQL standard), vérifié en confrontant deux plans
    # différents sur ce cas réel. Doit désormais renvoyer le même sortant à
    # chaque appel.
    resultats = [detecter_sortant("05781313100026", "72227000")["siren_sortant"] for _ in range(3)]
    assert len(set(resultats)) == 1