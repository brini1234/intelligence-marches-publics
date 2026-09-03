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


def test_echeance_estimee_provient_bien_du_marche_du_sortant_retourne():
    # Régression (bug trouvé par revue de code indépendante le 03/09/2026) :
    # `derniere_entree` était pris comme `chaine[-1]` (dernier élément après
    # tri stable croissant par date_notification, dédupliqué par uid) plutôt
    # que l'entrée correspondant au marché de `marche_actuel` (résultats[0],
    # tie-break siren_titulaire ASC côté SQL). Quand plusieurs marchés
    # DISTINCTS du même acheteur/CPV partagent exactement la même
    # date_notification maximale (vérifié en base réelle : jusqu'à 58 uid à
    # égalité un même jour), ces deux tie-breaks pouvaient désigner des
    # marchés différents -- l'échéance affichée pour le sortant retourné
    # décrivait alors en réalité un AUTRE marché tié à la même date. Cas réel
    # reproduit : SIRET 25770538400044/CPV 72212900 -- avant correction,
    # date_expiration_estimee=2024-06-13 (durée 9 mois d'un marché tié)
    # plutôt que 2024-05-13 (durée réelle 8 mois du marché du sortant
    # retourné, notifié le 2023-09-13).
    resultat = detecter_sortant("25770538400044", "72212900")
    assert resultat["sortant_probable"] == "ARTAL TECHNOLOGIES"
    assert resultat["date_expiration_estimee"] == "2024-05-13"
    assert resultat["duree_source"] == "reelle"