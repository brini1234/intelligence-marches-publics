import sys
sys.path.append(".")
from connectors.boamp import _codes_cpv, _normaliser_enregistrement, rechercher_resultats_marche


def test_rechercher_resultats_marche_filtre_bien_le_cpv():
    # Bornée à quelques pages (max_pages) : ce test vérifie le filtrage,
    # pas le volume total (~136 000 avis nationaux, plusieurs minutes,
    # couvert séparément par scripts/charger_cache_boamp.py).
    resultats = rechercher_resultats_marche(prefixe_cpv="72", max_pages=5)
    assert len(resultats) > 0
    hors_perimetre = [
        r["idweb"] for r in resultats
        if not any(c.startswith("72") for c in r["codes_cpv"])
    ]
    assert hors_perimetre == [], f"avis hors périmètre CPV 72xxxxxx : {hors_perimetre}"


def test_codes_cpv_gere_dict_et_liste_de_dicts():
    # Marché mono-lot : OBJET.CPV est un dict {"PRINCIPAL": ...}
    assert _codes_cpv({"OBJET": {"CPV": {"PRINCIPAL": "72220000"}}}) == ["72220000"]
    # Marché multi-lots : OBJET.CPV est une LISTE de dicts (un par lot) —
    # forme vérifiée en conditions réelles le 31/08/2026, jamais supposée.
    assert _codes_cpv({"OBJET": {"CPV": [{"PRINCIPAL": "34928400"}, {"PRINCIPAL": "39142000"}]}}) == [
        "34928400", "39142000",
    ]
    assert _codes_cpv({"OBJET": {}}) == []
    assert _codes_cpv({}) == []


def test_normaliser_enregistrement_gere_donnees_absentes_ou_invalides():
    # Dégradation gracieuse : un avis sans champ "donnees" exploitable ne
    # doit jamais faire planter toute la pagination.
    assert _normaliser_enregistrement({}) is None
    assert _normaliser_enregistrement({"donnees": "pas du json valide"}) is None
    assert _normaliser_enregistrement({"donnees": "[]"}) is None  # JSON valide mais pas un objet


def test_normaliser_enregistrement_extrait_les_champs_utiles():
    champs = {
        "idweb": "23-000001",
        "nomacheteur": "TEST ACHETEUR",
        "titulaire": ["TEST TITULAIRE"],
        "objet": "Objet du marché",
        "dateparution": "2023-11-12",
        "code_departement": ["75"],
        "donnees": '{"OBJET": {"CPV": {"PRINCIPAL": "72220000"}}}',
    }
    resultat = _normaliser_enregistrement(champs)
    assert resultat["idweb"] == "23-000001"
    assert resultat["codes_cpv"] == ["72220000"]
    assert resultat["code_departement"] == "75"
