import sys
sys.path.append(".")

from db.connection import get_engine
from scripts.resolution_identite import resoudre_par_continuite_acheteur
from scripts.agent_investigation_identite import investiguer_via_historique_sirene

# Couple acheteur/titulaire réel, déjà en base (silver_attributions/silver_marches).
SIRET_ACHETEUR_REEL = "13000501000033"
SIREN_TITULAIRE_REEL = "812535284"
SIRET_TITULAIRE_REEL = "81253528400044"

# France Télécom a changé de raison sociale pour Orange en 2013, même SIREN
# (vérifié en direct sur l'API SIRENE, cf. docstring de agent_investigation_identite.py).
SIREN_FRANCE_TELECOM_ORANGE = "380129866"


def test_continuite_retrouve_le_titulaire_deja_connu_de_cet_acheteur():
    # Homonymie simulée : le vrai SIREN déjà connu de cet acheteur, plus un
    # SIREN sans aucun rapport — seule la continuité doit permettre de trancher.
    engine = get_engine()
    with engine.connect() as connexion:
        resultat = resoudre_par_continuite_acheteur(
            [SIREN_TITULAIRE_REEL, "999999999"], SIRET_ACHETEUR_REEL, connexion
        )
    assert resultat is not None
    assert resultat["siret"] == SIRET_TITULAIRE_REEL
    assert resultat["methode"] == "investigation_continuite"
    assert resultat["score_confiance"] < 1.0  # jamais une certitude pleine


def test_continuite_ne_tranche_pas_sans_signal():
    # Aucun des deux candidats n'a de lien connu avec cet acheteur -> pas de pick.
    engine = get_engine()
    with engine.connect() as connexion:
        resultat = resoudre_par_continuite_acheteur(
            ["999999998", "999999999"], SIRET_ACHETEUR_REEL, connexion
        )
    assert resultat is None


def test_historique_sirene_retrouve_orange_et_ignore_les_homonymes_actuels():
    # Un seul appel API (pas deux) pour les deux assertions : SIREN 441965027
    # est réellement nommé "FRANCE TELECOM" AUJOURD'HUI (pas un renommage) et
    # ne doit jamais être confondu avec le vrai changement de raison sociale
    # (SIREN 380129866, ex-France Télécom devenu Orange en 2013).
    engine = get_engine()
    with engine.connect() as connexion:
        resultat = investiguer_via_historique_sirene("FRANCE TELECOM", connexion)
    assert resultat is not None
    assert resultat["siren"] == SIREN_FRANCE_TELECOM_ORANGE
    assert resultat["siren"] != "441965027"
    assert resultat["methode"] == "investigation_historique_denomination"
    assert resultat["score_confiance"] < 1.0


def test_historique_sirene_renvoie_none_sur_nom_invente():
    resultat = investiguer_via_historique_sirene("ENTREPRISE COMPLETEMENT INVENTEE XYZ123")
    assert resultat is None
