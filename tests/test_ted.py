import sys
sys.path.append(".")
from connectors.ted import exporter_perimetre_complet, _premiere_valeur_multilingue


def test_exporter_perimetre_complet_retourne_des_avis():
    notices = exporter_perimetre_complet()
    assert len(notices) > 0
    assert notices[0]["publication_number"] is not None
    assert notices[0]["code_cpv"].startswith("72")


def test_premiere_valeur_multilingue_gere_listes_et_chaines():
    # buyer-name / winner-name : une liste par langue
    assert _premiere_valeur_multilingue({"fra": ["ACME"], "eng": ["ACME"]}) == "ACME"
    # notice-title : une chaîne directe par langue (piège rencontré en prod :
    # indexer [0] sur une chaîne renvoie son premier caractère, pas le texte)
    assert _premiere_valeur_multilingue({"fra": "France – Services...", "eng": "France - Services..."}) == "France – Services..."
    # absence de français : repli sur la première langue disponible
    assert _premiere_valeur_multilingue({"eng": ["ACME"]}) == "ACME"
    assert _premiere_valeur_multilingue({}) is None
    assert _premiere_valeur_multilingue(None) is None
