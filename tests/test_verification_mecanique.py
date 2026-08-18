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


def test_fiche_contient_les_5_elements_du_bloc_de_decision():
    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    cles = [f["cle"] for f in fiche["faits"]]
    assert "titulaire_actuel" in cles
    assert "concurrents_observes" in cles
    assert "fourchette_prix_min" in cles
    assert "fourchette_prix_max" in cles
    assert "ponderation_acheteur" in cles


def test_verbaliser_gere_famille_sans_aucun_montant_ou_elargie():
    # Cas réel (marché TED sans montant, acheteur 13000208200043, CPV
    # 72267000) : la famille exacte n'a aucun montant publié. Depuis
    # l'agent d'expansion (scripts/agent_expansion_couverture.py, S6),
    # une famille aussi pauvre (nb_marches_famille < 2) déclenche un
    # élargissement CPV parent qui peut retrouver un montant sur un
    # périmètre plus large — comportement voulu, pas une régression. Ce
    # qui compte réellement : jamais de plantage en formatant None comme
    # un nombre, et une couverture toujours honnête dans les deux cas.
    fiche = construire_fiche_de_faits("13000208200043", "72267000")
    valeurs = {f["cle"]: f for f in fiche["faits"]}
    prix_min = valeurs["fourchette_prix_min"]
    texte = verbaliser(fiche)  # ne doit jamais planter, quel que soit le cas

    if prix_min["valeur"] is None:
        assert prix_min["couverture"] == 0.0
        assert "non disponible" in texte
    else:
        # Élargi par l'agent : la trace de l'élargissement doit être présente
        # et le fait ne doit jamais afficher une couverture pleine, puisqu'il
        # dépend d'un périmètre plus large que l'acheteur/CPV exact demandé.
        assert "elargissement_applique" in valeurs
        assert prix_min["couverture"] < 1.0