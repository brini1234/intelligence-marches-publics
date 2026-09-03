import sys
sys.path.append(".")
from scripts.fiche_de_faits import _valider, construire_fiche_de_faits, MAX_CONCURRENTS_AFFICHES
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


def test_acheteurs_comparables_elargissent_reellement_concurrents_et_prix():
    # Régression (bug trouvé par revue de code indépendante le 03/09/2026) :
    # l'agent d'expansion (scripts/agent_expansion_couverture.py) calculait
    # une liste d'acheteurs comparables mais elle n'était jamais utilisée --
    # concurrents_observes/fourchette_prix restaient strictement ceux du
    # seul acheteur d'origine, contrairement à ce que le docstring du module
    # et la documentation affirmaient. Cas réel : ce couple acheteur/CPV n'a
    # que 22 marchés en propre mais des dizaines de concurrents une fois
    # les acheteurs comparables (même NAF) fusionnés dans les statistiques.
    fiche = construire_fiche_de_faits("05781313100026", "72413000")
    valeurs = {f["cle"]: f for f in fiche["faits"]}

    fait_concurrents = valeurs["concurrents_observes"]
    # Plafonné à MAX_CONCURRENTS_AFFICHES + 1 ligne de décompte (sujet,
    # section 2 : bloc de décision lisible en 30 secondes) -- jamais un mur
    # de dizaines de noms, jamais non plus une troncature silencieuse.
    assert len(fait_concurrents["valeur"]) == MAX_CONCURRENTS_AFFICHES + 1
    assert fait_concurrents["valeur"][-1].startswith("... et ")

    # Couverture dégradée (moitié de la couverture normale) car les
    # statistiques proviennent en partie d'acheteurs comparables, pas
    # seulement de l'acheteur exact demandé -- jamais présentée avec la
    # même certitude qu'une requête directe.
    assert 0.0 < fait_concurrents["couverture"] < 0.33
    assert 0.0 < valeurs["fourchette_prix_min"]["couverture"] < 0.33

    # Le sortant lui-même reste celui de l'acheteur d'origine uniquement --
    # jamais influencé par les acheteurs comparables (docstring de
    # agent_expansion_couverture.py : "jamais le sortant").
    assert valeurs["titulaire_actuel"]["valeur"] == "HYDRO GEOTECHNIQUE SUD EST (HYDRO-GEO)"
