import sys
sys.path.append(".")
from scripts.fiche_de_faits import construire_fiche_de_faits
from scripts.verbaliser import verbaliser
from scripts.verification_mecanique import verifier_texte


def test_texte_genere_a_partir_de_la_fiche_est_valide():
    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    texte = verbaliser(fiche)
    resultat = verifier_texte(texte, fiche)
    assert resultat["valide"] is True


def test_texte_avec_chiffre_invente_est_rejete():
    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    texte_invente = "Le marché a été attribué pour un montant de 999999999 euros."
    resultat = verifier_texte(texte_invente, fiche)
    assert resultat["valide"] is False
    assert "999999999" in resultat["nombres_non_justifies"]


def test_verbaliser_gere_absence_de_donnees():
    fiche = construire_fiche_de_faits("00000000000000", "99999999")
    texte = verbaliser(fiche)
    assert "insuffisantes" in texte.lower()    