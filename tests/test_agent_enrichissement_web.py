import sys
sys.path.append(".")

from db.connection import get_engine
from connectors.web_ouvert import rechercher_web
from scripts.agent_enrichissement_web import enrichir_identite_via_web, _sirens_mentionnes

# Entreprise réelle sans ambiguïté (jeu de test de résolution d'identité,
# tests/donnees/jeu_test_resolution_identite.csv, type_cas=niveau3_flou).
NOM_SANS_AMBIGUITE = "AXANDE"
SIREN_ATTENDU = "450813100"


def test_rechercher_web_retourne_des_resultats():
    resultats = rechercher_web("CAPGEMINI SIREN")
    assert len(resultats) > 0


def test_rechercher_web_gere_une_requete_qui_ne_donne_rien_de_structure():
    # Dégradation gracieuse : même une requête absurde ne doit jamais lever
    # d'exception, au pire renvoyer une liste vide ou sans SIREN exploitable.
    resultats = rechercher_web("zzzqqqxxx11223344 inexistant")
    assert isinstance(resultats, list)


def test_sirens_mentionnes_extrait_les_formats_courants():
    assert _sirens_mentionnes("SIREN 508 008 984") == ["508008984"]
    assert _sirens_mentionnes("SIREN : 508008984 et rien d'autre") == ["508008984"]
    # Un SIREN à l'intérieur d'un SIRET à 14 chiffres n'a pas de frontière
    # de mot après le 9e chiffre : ne doit pas être extrait par erreur
    # (sinon un SIRET mal formé pourrait laisser croire à 2 sources
    # indépendantes alors qu'il n'y en a qu'une).
    assert _sirens_mentionnes("50800898400025") == []


def test_enrichir_identite_via_web_resout_un_cas_sans_ambiguite():
    engine = get_engine()
    with engine.connect() as connexion:
        resultat = enrichir_identite_via_web(NOM_SANS_AMBIGUITE, connexion)
    assert resultat is not None
    assert resultat["siren"] == SIREN_ATTENDU
    assert resultat["methode"] == "enrichissement_web"
    assert resultat["score_confiance"] < 0.55  # le score le plus bas de la hiérarchie


def test_enrichir_identite_via_web_gere_absence_totale_de_signal():
    engine = get_engine()
    with engine.connect() as connexion:
        resultat = enrichir_identite_via_web("ENTREPRISE COMPLETEMENT INVENTEE XYZ123", connexion)
    assert resultat is None


def test_enrichir_identite_via_web_nom_vide_ne_plante_pas():
    engine = get_engine()
    with engine.connect() as connexion:
        assert enrichir_identite_via_web("", connexion) is None
        assert enrichir_identite_via_web(None, connexion) is None
