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


def test_agent_elargit_reellement_les_statistiques_via_acheteurs_comparables():
    # Régression (bug trouvé par revue de code indépendante le 03/09/2026) :
    # les axes "acheteurs comparables"/"périmètre géographique" calculaient
    # une liste d'acheteurs comparables et la traçaient dans
    # expansions_appliquees, mais cette liste n'était ensuite jamais
    # utilisée -- contrairement à ce que le docstring du module et la
    # documentation (README, rapport de stage) affirment ("statistiques de
    # prix/concurrents élargies"). Cas réel : même acheteur/CPV que
    # test_agent_elargit_une_famille_pauvre ci-dessus, dont l'axe CPV parent
    # ne suffit pas seul à couvrir tout le potentiel d'élargissement --
    # l'agent trouve aussi des acheteurs comparables (même NAF) dont
    # l'historique doit désormais alimenter historique_elargi.
    resultat = agent_expansion_couverture("05781313100026", "72413000")
    assert resultat["type"] == "resultat"
    assert resultat["acheteurs_comparables"]
    assert resultat["historique_elargi"]
    # Jamais utilisé pour le sortant lui-même (docstring du module) :
    # aucune entrée d'historique_elargi ne porte de date_notification/uid,
    # qui n'existent que sur les entrées venant de detecter_sortant().
    for entree in resultat["historique_elargi"]:
        assert set(entree.keys()) == {"denomination", "montant", "etat_administratif"}


def test_agent_ne_plante_pas_sur_acheteur_connu_avec_zero_marche_sur_le_cpv_exact():
    # Régression (bug trouvé par revue de code indépendante le 20/08/2026) :
    # detecter_sortant() ne porte pas la clé "nb_marches_famille" dans son
    # retour minimal quand aucun marché n'est trouvé pour l'acheteur/CPV
    # exact demandé -- un accès direct par crochets plantait (KeyError) dès
    # qu'un acheteur connu (a un historique global) était interrogé sur un
    # CPV qu'il n'a jamais utilisé, le cas le plus courant en pratique.
    # Cour des Comptes a un historique réel (13 marchés) mais aucun sur ce
    # CPV précis.
    resultat = agent_expansion_couverture("11000028800016", "45000000")
    assert resultat["type"] in ("resultat", "donnees_insuffisantes")
