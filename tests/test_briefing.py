import json
import sys

sys.path.append(".")

import pytest

from scripts.briefing import EntreeAmbigue, deduire_cpv, main, resoudre_acheteur


def test_acheteur_resolu_par_siret_et_par_nom_exact():
    assert resoudre_acheteur("11000028800016") == ("11000028800016", "COUR DES COMPTES")
    assert resoudre_acheteur("cour des comptes") == ("11000028800016", "COUR DES COMPTES")


def test_nom_acheteur_ambigu_n_est_jamais_tranche_arbitrairement():
    with pytest.raises(EntreeAmbigue, match="préciser le SIRET"):
        resoudre_acheteur("commune")


def test_objet_hors_sujet_est_refuse_plutot_que_rattache_a_un_cpv():
    with pytest.raises(EntreeAmbigue, match="trop éloigné"):
        deduire_cpv("zzzz qqqq")


def test_objet_en_texte_libre_retrouve_le_cpv_du_marche():
    deduction = deduire_cpv("audit des systèmes d'information pour la certification des comptes")
    assert deduction["code_cpv"] == "72220000"
    assert 0 < deduction["voisins_concordants"] <= deduction["voisins_total"]


def test_cli_produit_bloc_fiche_json_et_rapport_detaille(tmp_path, capsys):
    chemin_json, chemin_rapport = tmp_path / "fiche.json", tmp_path / "rapport.md"
    code = main(["--acheteur", "11000028800016", "--cpv", "72220000",
                 "--json", str(chemin_json), "--rapport", str(chemin_rapport)])
    assert code == 0
    assert "Sortant probable" in capsys.readouterr().out

    fiche = json.loads(chemin_json.read_text(encoding="utf-8"))
    assert fiche["faits"] and fiche["marches_support"]

    rapport = chemin_rapport.read_text(encoding="utf-8")
    assert "## Faits, provenance et couverture" in rapport
    assert "Vérification mécanique (nombres, noms, dates présents dans la fiche) : valide" in rapport
    assert fiche["marches_support"][0] in rapport


def test_cli_retourne_2_sur_entree_ambigue(capsys):
    assert main(["--acheteur", "commune", "--cpv", "72220000"]) == 2
    assert "préciser le SIRET" in capsys.readouterr().err
