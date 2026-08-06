import sys
sys.path.append(".")
from connectors.ted import exporter_perimetre_complet, _premiere_valeur_multilingue


def test_exporter_perimetre_complet_retourne_des_avis():
    notices = exporter_perimetre_complet()
    assert len(notices) > 0
    assert notices[0]["publication_number"] is not None
    # Sur TOUS les avis, pas seulement le premier : un avis TED porte souvent
    # plusieurs codes CPV, prendre le premier élément de la liste sans
    # vérifier qu'il appartient au périmètre a déjà laissé passer des
    # marchés hors 72xxxxxx en base (45/273 constatés) sans que ce test ne
    # le détecte, faute de vérifier autre chose que notices[0].
    sans_cpv_perimetre = [n["publication_number"] for n in notices if not (n["code_cpv"] or "").startswith("72")]
    assert sans_cpv_perimetre == [], f"avis hors périmètre CPV 72xxxxxx : {sans_cpv_perimetre}"


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
