import sys
sys.path.append(".")

from db.connection import get_engine
from scripts.agent_expansion_couverture import (
    agent_expansion_couverture,
    detecter_centrale_achat,
)

# UGAP, réelle en base (README/rapport : centrale d'achat vérifiée).
SIRET_UGAP = "77605646700587"


def test_detecter_centrale_achat_trouve_ugap():
    engine = get_engine()
    with engine.connect() as connexion:
        resultat = detecter_centrale_achat(SIRET_UGAP, connexion)
    assert resultat is not None
    assert resultat["centrale_detectee"] == "UGAP"


def test_detecter_centrale_achat_ne_matche_pas_un_acheteur_normal():
    engine = get_engine()
    with engine.connect() as connexion:
        # Cour des Comptes : acheteur réel, pas une centrale d'achat.
        resultat = detecter_centrale_achat("11000028800016", connexion)
    assert resultat is None


def test_agent_signale_centrale_achat_sans_expansion():
    resultat = agent_expansion_couverture(SIRET_UGAP, "72000000")
    assert resultat["type"] == "centrale_achat"
    assert "UGAP" in resultat["message"] or "centrale" in resultat["message"].lower()


def test_agent_declare_donnees_insuffisantes_sur_acheteur_sans_historique():
    resultat = agent_expansion_couverture("00000000000000", "99999999")
    assert resultat["type"] == "donnees_insuffisantes"
    assert resultat["expansions_tentees"] == []


def test_agent_elargit_une_famille_pauvre():
    # Cas réel découvert en base : un seul marché sur ce CPV exact, mais
    # plusieurs sur le préfixe CPV plus large (72413000 -> 7241).
    resultat = agent_expansion_couverture("05781313100026", "72413000")
    assert resultat["type"] == "resultat"
    assert any(e["axe"] == "cpv_parent" for e in resultat["expansions_appliquees"])
    assert resultat["resultat_sortant"]["nb_marches_famille"] > 1
