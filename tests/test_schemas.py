import sys
sys.path.append(".")

import pytest
from pydantic import ValidationError

from scripts.schemas import BlocDeDecision, Fait, FicheDeFaits


def test_fiche_de_faits_valide_un_fait_normal():
    fiche = FicheDeFaits(
        faits=[{"cle": "titulaire_actuel", "valeur": "ORANGE", "provenance": "table entreprises", "couverture": 1.0}],
        couverture_globale=0.89,
        marches_support=["uid-1", "uid-2"],
    )
    assert fiche.faits[0].cle == "titulaire_actuel"


def test_fiche_de_faits_donnees_insuffisantes_sans_faits():
    fiche = FicheDeFaits(faits=[], couverture_globale=0.0, raison="acheteur sans historique")
    assert fiche.faits == []
    assert fiche.raison == "acheteur sans historique"


def test_fiche_de_faits_rejette_une_couverture_hors_bornes():
    with pytest.raises(ValidationError):
        FicheDeFaits(
            faits=[{"cle": "x", "valeur": "y", "provenance": "z", "couverture": 1.5}],
            couverture_globale=0.5,
        )


def test_fait_rejette_une_provenance_vide():
    with pytest.raises(ValidationError):
        Fait(cle="x", valeur="y", provenance="", couverture=0.5)


def test_fait_accepte_une_liste_de_concurrents():
    f = Fait(cle="concurrents_observes", valeur=["A (1/3)", "B (2/3)"], provenance="table attributions", couverture=0.66)
    assert f.valeur == ["A (1/3)", "B (2/3)"]


def test_bloc_de_decision_accepte_dix_lignes_maximum():
    bloc = BlocDeDecision(lignes=[f"ligne {i}" for i in range(10)])
    assert len(bloc.lignes) == 10


def test_bloc_de_decision_rejette_plus_de_dix_lignes():
    with pytest.raises(ValidationError):
        BlocDeDecision(lignes=[f"ligne {i}" for i in range(11)])


def test_bloc_de_decision_rejette_une_ligne_vide():
    with pytest.raises(ValidationError):
        BlocDeDecision(lignes=["une ligne valide", "   "])


def test_bloc_de_decision_rejette_liste_vide():
    with pytest.raises(ValidationError):
        BlocDeDecision(lignes=[])
