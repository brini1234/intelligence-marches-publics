import sys
sys.path.append(".")
from scripts.bloc_de_decision import construire_bloc_de_decision


def test_bloc_de_decision_respecte_la_limite_de_10_lignes():
    lignes = construire_bloc_de_decision("11000028800016", "72220000", "COUR DES COMPTES")
    assert len(lignes) <= 10


def test_bloc_de_decision_gere_absence_de_donnees():
    lignes = construire_bloc_de_decision("00000000000000", "99999999", "ACHETEUR INCONNU")
    assert len(lignes) <= 10
    assert any("INSUFFISANTES" in ligne for ligne in lignes)


def test_bloc_de_decision_gere_famille_sans_aucun_montant_publie():
    # Cas réel (marché TED sans montant) : ne doit jamais planter en
    # formatant None comme un nombre (`{prix_min:,.0f}` sur None). Depuis
    # l'agent d'expansion (S6), ce cas peut désormais être élargi et
    # retrouver un montant sur un périmètre plus large — la ligne
    # "Fourchette de prix" doit alors être correctement formatée (pas
    # planter), pas nécessairement rester "non disponible". La ligne
    # "Pondération de l'acheteur" contient toujours "non disponible"
    # (aucune source connectée ne la fournit) : on vise explicitement la
    # ligne fourchette de prix pour ne pas se reposer dessus par erreur.
    lignes = construire_bloc_de_decision("13000208200043", "72267000", "TEST")
    assert len(lignes) <= 10
    ligne_prix = next(l for l in lignes if l.startswith("Fourchette de prix"))
    assert "non disponible" in ligne_prix or "€" in ligne_prix