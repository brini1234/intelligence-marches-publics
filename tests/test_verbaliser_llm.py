import os
import sys

sys.path.append(".")

import httpx2
import pytest
import anthropic

from scripts.verbaliser import verbaliser
from scripts.verbaliser_llm import verbaliser_via_llm, MAX_TENTATIVES
from scripts.verification_mecanique import verifier_texte

FICHE_RICHE = {
    "faits": [
        {"cle": "titulaire_actuel", "valeur": "ACME SAS", "provenance": "test", "couverture": 1.0},
        {"cle": "date_dernier_marche", "valeur": "2024-01-01", "provenance": "test", "couverture": 1.0},
        {"cle": "date_expiration_estimee", "valeur": "2028-01-01", "provenance": "test", "couverture": 1.0},
        {"cle": "concurrents_observes", "valeur": ["ORANGE", "BOUYGUES"], "provenance": "test", "couverture": 1.0},
        {"cle": "nombre_marches_historique", "valeur": 3, "provenance": "test", "couverture": 1.0},
        {"cle": "fourchette_prix_min", "valeur": 100000, "provenance": "test", "couverture": 1.0},
        {"cle": "fourchette_prix_max", "valeur": 200000, "provenance": "test", "couverture": 1.0},
        {"cle": "ponderation_acheteur", "valeur": "non disponible", "provenance": "test", "couverture": 0.0},
    ],
    "couverture_globale": 0.8,
    "raison": None,
    "marches_support": ["uid_test"],
}

FICHE_VIDE = {"faits": [], "couverture_globale": 0.0, "raison": "acheteur sans historique", "marches_support": None}


class _FakeBloc:
    def __init__(self, texte):
        self.type = "text"
        self.text = texte


class _FakeReponse:
    def __init__(self, texte, stop_reason="end_turn"):
        self.content = [_FakeBloc(texte)]
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, textes_ou_exceptions):
        self._items = list(textes_ou_exceptions)
        self.appels = 0
        # Capture chaque appel réel (kwargs bruts) pour que les tests
        # puissent vérifier CE QUI A ÉTÉ ENVOYÉ, pas seulement le résultat
        # final — un mock qui ignore kwargs["model"] masquerait un mauvais
        # nom de modèle indéfiniment (signalé par l'utilisateur : aucun des
        # 7 tests précédents ne vérifiait le paramètre `model` transmis).
        self.kwargs_appels = []

    def create(self, **kwargs):
        self.kwargs_appels.append(kwargs)
        item = self._items[self.appels]
        self.appels += 1
        if isinstance(item, Exception):
            raise item
        if isinstance(item, _FakeReponse):
            return item
        return _FakeReponse(item)


class _FakeClient:
    def __init__(self, textes_ou_exceptions):
        self.messages = _FakeMessages(textes_ou_exceptions)


def test_fiche_vide_ne_declenche_aucun_appel_llm():
    # Court-circuit voulu : pas de faits -> pas d'appel réseau à payer pour
    # une phrase fixe (cf. docstring de verbaliser_via_llm).
    client = _FakeClient([])
    texte = verbaliser_via_llm(FICHE_VIDE, client=client)
    assert texte == verbaliser(FICHE_VIDE)
    assert client.messages.appels == 0


def test_appel_llm_transmet_le_modele_haiku_exact():
    # Chaîne littérale, PAS une réimportation de MODELE_LLM comparée à
    # elle-même (ce qui ne détecterait jamais une faute de frappe dans la
    # constante) — vérifie ce qui est réellement envoyé à l'API.
    client = _FakeClient(["texte quelconque, peu importe ici"])
    verbaliser_via_llm(FICHE_RICHE, client=client)
    assert client.messages.kwargs_appels[0]["model"] == "claude-haiku-4-5"


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY non configurée")
def test_modele_haiku_existe_reellement_sur_l_api_anthropic():
    # Vérification la plus forte possible sur le nom de modèle : interroge
    # directement l'API Models d'Anthropic plutôt que de faire confiance à
    # une table mise en cache. Si "claude-haiku-4-5" n'existe pas ou plus
    # côté API, ce test échoue avec l'erreur réelle de l'API (404 ou
    # équivalent), pas une supposition.
    from scripts.verbaliser_llm import MODELE_LLM
    client = anthropic.Anthropic()
    modele = client.models.retrieve(MODELE_LLM)
    assert modele.id == MODELE_LLM


def test_texte_llm_valide_du_premier_coup_est_retourne_tel_quel():
    texte_llm = "Titulaire actuel probable : ACME SAS (dernier marché notifié le 2024-01-01, échéance estimée : 2028-01-01). Concurrents observés : ORANGE, BOUYGUES. Fourchette de prix constatée : 100000 € à 200000 € (n=3, indicatif). Pondération de l'acheteur : non disponible. Basé sur 3 marché(s) similaire(s) (couverture globale : 80%)."
    client = _FakeClient([texte_llm])
    texte = verbaliser_via_llm(FICHE_RICHE, client=client)
    assert texte == texte_llm
    assert client.messages.appels == 1
    assert verifier_texte(texte, FICHE_RICHE)["valide"] is True


def test_texte_invalide_puis_valide_declenche_bien_une_regeneration():
    # Premier essai : le "LLM" invente un montant absent de la fiche.
    # Deuxième essai : texte conforme. Vérifie que la boucle de
    # génère->vérifie->régénère du sujet (section 4) fonctionne vraiment,
    # pas seulement sur une chaîne fabriquée à la main comme dans
    # tests/test_verification_mecanique.py.
    texte_invente = "Le marché a été attribué pour 999999999 euros à ACME SAS."
    texte_correct = "Titulaire actuel probable : ACME SAS (dernier marché notifié le 2024-01-01, échéance estimée : 2028-01-01). Concurrents observés : ORANGE, BOUYGUES. Fourchette de prix constatée : 100000 € à 200000 € (n=3, indicatif). Pondération de l'acheteur : non disponible. Basé sur 3 marché(s) similaire(s) (couverture globale : 80%)."
    client = _FakeClient([texte_invente, texte_correct])
    texte = verbaliser_via_llm(FICHE_RICHE, client=client)
    assert texte == texte_correct
    assert client.messages.appels == 2
    assert verifier_texte(texte, FICHE_RICHE)["valide"] is True


def test_echec_repete_replie_sur_le_gabarit_deterministe():
    # Le "LLM" hallucine à chaque tentative -> après MAX_TENTATIVES essais,
    # repli sur verbaliser() (déterministe), jamais un texte non vérifié
    # livré (sujet, section 4).
    texte_invente = "999999999 euros, jamais vu ce chiffre dans la fiche."
    client = _FakeClient([texte_invente] * MAX_TENTATIVES)
    texte = verbaliser_via_llm(FICHE_RICHE, client=client)
    assert texte == verbaliser(FICHE_RICHE)
    assert client.messages.appels == MAX_TENTATIVES
    assert verifier_texte(texte, FICHE_RICHE)["valide"] is True


def test_erreur_reseau_replie_gracieusement_sans_planter():
    erreur = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    client = _FakeClient([erreur])
    texte = verbaliser_via_llm(FICHE_RICHE, client=client)
    assert texte == verbaliser(FICHE_RICHE)


def test_refus_du_modele_replie_gracieusement():
    client = _FakeClient([_FakeReponse("", stop_reason="refusal")])
    texte = verbaliser_via_llm(FICHE_RICHE, client=client)
    assert texte == verbaliser(FICHE_RICHE)


def test_sans_cle_api_replie_gracieusement(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    texte = verbaliser_via_llm(FICHE_RICHE, client=None)
    assert texte == verbaliser(FICHE_RICHE)


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY non configurée")
def test_llm_reel_produit_toujours_un_texte_valide_sur_plusieurs_cas():
    # Le seul test de ce fichier qui appelle réellement claude-opus-5 : un
    # modèle qui peut effectivement halluciner, pas une chaîne fabriquée à
    # la main. L'invariant testé n'est pas "le LLM ne se trompe jamais"
    # (il peut), mais "le texte FINAL livré est toujours valide" (grâce à
    # la boucle vérifie->régénère->repli).
    fiches = [FICHE_RICHE, FICHE_VIDE]
    for fiche in fiches:
        texte = verbaliser_via_llm(fiche)
        assert texte, "jamais de texte vide"
        assert verifier_texte(texte, fiche)["valide"] is True
