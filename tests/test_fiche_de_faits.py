import sys
sys.path.append(".")
from scripts.fiche_de_faits import _valider, construire_fiche_de_faits
from scripts.bloc_de_decision import construire_bloc_de_decision


def test_valider_conserve_la_cle_valeur_quand_elle_est_none():
    # Bug trouvé en revue (02/09/2026) : model_dump(..., exclude_none=True)
    # supprimait la clé "valeur" de tout Fait dont la valeur est
    # légitimement None (ex. fourchette de prix sans montant publié),
    # provoquant un KeyError dans scripts/bloc_de_decision.py qui y accède
    # sans .get(). La clé doit rester présente, avec la valeur null.
    fiche = _valider({
        "faits": [
            {"cle": "fourchette_prix_min", "valeur": None, "provenance": "test", "couverture": 0.0},
        ],
        "couverture_globale": 0.0,
        "marches_support": ["uid_test"],
    })
    assert "valeur" in fiche["faits"][0]
    assert fiche["faits"][0]["valeur"] is None
    assert "raison" not in fiche  # champ racine réellement absent, toujours omis


def test_bloc_de_decision_ne_plante_pas_sur_famille_reelle_sans_aucun_montant():
    # Cas réel vérifié en base (acheteur/CPV avec 4 marchés, aucun montant
    # publié sur aucun) : reproduisait le KeyError ci-dessus avant
    # correction, indépendamment de tout élargissement par l'agent
    # d'expansion (contrairement au cas déjà couvert dans
    # test_bloc_de_decision.py, qui peut être élargi et retrouver un
    # montant selon l'état de la base).
    lignes = construire_bloc_de_decision("26750004902888", "72250000", "TEST")
    assert len(lignes) <= 10
    ligne_prix = next(l for l in lignes if l.startswith("Fourchette de prix"))
    assert "non disponible" in ligne_prix


def test_duree_restante_mois_absente_degrade_sa_propre_couverture():
    # Bug trouvé en revue (02/09/2026) : le fait duree_restante_mois
    # gardait la couverture pleine du sortant (`score`) même quand sa
    # valeur est None (cas de tout marché TED, qui ne publie jamais ce
    # champ) — gonflant couverture_globale sans qu'aucune section
    # affichée ne le laisse deviner, contrairement à couverture_expiration
    # qui dégrade déjà correctement dans le même cas.
    fiche = construire_fiche_de_faits("22910228000018", "72000000")
    valeurs = {f["cle"]: f for f in fiche["faits"]}
    fait_duree = valeurs["duree_restante_mois"]
    if fait_duree["valeur"] is None:
        assert fait_duree["couverture"] == 0.0
