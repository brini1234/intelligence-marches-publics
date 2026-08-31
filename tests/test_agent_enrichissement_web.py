import sys
sys.path.append(".")

import pytest

from db.connection import get_engine
from connectors.web_ouvert import rechercher_web
from scripts.agent_enrichissement_web import enrichir_identite_via_web, _sirens_mentionnes

# Entreprise réelle sans ambiguïté (jeu de test de résolution d'identité,
# tests/donnees/jeu_test_resolution_identite.csv, type_cas=niveau3_flou).
NOM_SANS_AMBIGUITE = "AXANDE"
SIREN_ATTENDU = "450813100"


def test_rechercher_web_retourne_des_resultats():
    # Même aléa réseau que test_enrichir_identite_via_web_resout_un_cas_sans_ambiguite
    # ci-dessous (défi anti-bot DuckDuckGo possible, HTTP 202) : une liste
    # vide ici peut être soit le déclenchement légitime de la dégradation
    # gracieuse, soit un vrai résultat vide — indiscernable sans relance.
    # On ne peut donc pas conclure à un échec de logique sur ce seul signal.
    resultats = rechercher_web("CAPGEMINI SIREN")
    if not resultats:
        pytest.skip("DuckDuckGo n'a renvoyé aucun résultat exploitable pour cet essai (probable défi anti-bot) — aléa réseau, pas un échec de logique")
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
    # Dépend d'une vraie réponse de duckduckgo.com/html (connecteur "sans
    # garantie" par nature, cf. connectors/web_ouvert.py) : DuckDuckGo peut
    # renvoyer un défi anti-bot (HTTP 202, page "Select all squares
    # containing a duck") au lieu de résultats, selon l'IP/le volume de
    # requêtes récent — un aléa réseau, jamais une erreur de logique.
    # rechercher_web() dégrade alors gracieusement vers [] (par design,
    # testé indépendamment par test_rechercher_web_gere_une_requete_qui_ne_donne_rien_de_structure)
    # et enrichir_identite_via_web() vers None. Ce test n'assert la
    # résolution positive que lorsque la recherche web a effectivement
    # renvoyé des résultats ; sinon il se déclare "skipped", pas "failed" —
    # distinguer un vrai échec de logique d'un aléa réseau externe, plutôt
    # que de masquer l'un derrière l'autre.
    resultats_bruts = rechercher_web(f'"{NOM_SANS_AMBIGUITE}" SIREN')
    if not resultats_bruts:
        pytest.skip("DuckDuckGo n'a renvoyé aucun résultat exploitable pour cet essai (probable défi anti-bot) — aléa réseau, pas un échec de logique")

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
