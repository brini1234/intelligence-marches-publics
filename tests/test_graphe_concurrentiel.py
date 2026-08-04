import sys
sys.path.append(".")
from sqlalchemy import text
from db.connection import get_engine
from scripts.graphe_concurrentiel import co_titulaires_transitifs, chaine_marches_acheteur


def test_co_titulaires_transitifs_sur_accord_cadre_reel():
    """Régression : l'accord-cadre multi-titulaires connu (Partie 1) doit
    apparaître comme groupement direct entre ses membres."""
    with get_engine().connect() as connexion:
        ligne = connexion.execute(text("""
            SELECT siren_titulaire FROM attributions
            GROUP BY uid_marche, siren_titulaire
            HAVING (SELECT COUNT(*) FROM attributions a2 WHERE a2.uid_marche = attributions.uid_marche) > 3
            LIMIT 1
        """)).fetchone()
    assert ligne is not None, "aucun accord-cadre multi-attributaires en base pour tester"

    resultats = co_titulaires_transitifs(ligne.siren_titulaire, profondeur_max=1)
    assert len(resultats) > 0
    for r in resultats:
        assert r["profondeur"] == 1
        assert r["siren"] != ligne.siren_titulaire


def test_co_titulaires_transitifs_siren_inconnu_ne_plante_pas():
    assert co_titulaires_transitifs("000000000") == []


def test_chaine_marches_acheteur_triee_par_date():
    with get_engine().connect() as connexion:
        ligne = connexion.execute(text("""
            SELECT siret_acheteur, code_cpv FROM marches
            GROUP BY siret_acheteur, code_cpv
            HAVING COUNT(*) > 2
            LIMIT 1
        """)).fetchone()
    assert ligne is not None

    chaine = chaine_marches_acheteur(ligne.siret_acheteur, ligne.code_cpv)
    dates = [m["date_notification"] for m in chaine]
    assert dates == sorted(dates)
    assert [m["position_chaine"] for m in chaine] == list(range(1, len(chaine) + 1))
