import sys
sys.path.append(".")
from scripts.resolution_identite import (
    normaliser_nom,
    resoudre_par_normalisation,
)


def test_espaces_internes_recomposent_un_siret():
    resultats = resoudre_par_normalisation("444 495 774 00531")
    assert resultats == [{"siret": "44449577400531", "siren": "444495774", "methode": "espaces", "pays_etranger": None}]


def test_prefixe_label_retire_avant_parsing():
    resultats = resoudre_par_normalisation("SIRET : 479 766 842 00724")
    assert resultats[0]["siret"] == "47976684200724"
    assert resultats[0]["methode"] == "espaces"


def test_champ_multivaleurs_extrait_plusieurs_siret():
    resultats = resoudre_par_normalisation("49337893900166 , 41859545000168, 31506794200088")
    assert [r["siret"] for r in resultats] == ["49337893900166", "41859545000168", "31506794200088"]


def test_siren_seul_neuf_chiffres():
    resultats = resoudre_par_normalisation("378615363")
    assert resultats == [{"siret": None, "siren": "378615363", "methode": "siren_seul", "pays_etranger": None}]


def test_tva_intracommunautaire_francaise_extrait_le_siren():
    resultats = resoudre_par_normalisation("FR85479766842")
    assert resultats == [{"siret": None, "siren": "479766842", "methode": "tva_fr", "pays_etranger": None}]


def test_tva_etrangere_jamais_confondue_avec_un_siren_francais():
    resultats = resoudre_par_normalisation("ESB67590687")
    assert len(resultats) == 1
    assert resultats[0]["methode"] == "etranger"
    assert resultats[0]["siren"] is None
    assert resultats[0]["pays_etranger"] == "ES"


def test_identifiant_sans_structure_reconnue_ne_produit_rien():
    # Identifiant interne TED sans structure exploitable : le niveau 2 ne
    # doit rien inventer, seul le niveau 3 (flou, testé séparément avec la
    # base réelle) peut éventuellement résoudre via le nom.
    assert resoudre_par_normalisation("1768215-1-1-1") == []


def test_normaliser_nom_retire_formes_juridiques_et_accents():
    assert normaliser_nom("Société Générale SA") == "SOCIETE GENERALE"
    assert normaliser_nom("ARTSOFT SARL") == "ARTSOFT"


def test_normaliser_nom_vide_retourne_chaine_vide():
    assert normaliser_nom("") == ""
    assert normaliser_nom(None) == ""
