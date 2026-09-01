import sys
sys.path.append(".")
from sqlalchemy import text
from db.connection import get_engine


def test_silver_marches_sans_doublon_de_uid():
    """La déduplication silver (sujet, S2) : une seule ligne par uid, même
    si bronze contient plusieurs versions/lignes pour le même marché."""
    with get_engine().begin() as connexion:
        total = connexion.execute(text("SELECT COUNT(*) FROM silver_marches")).scalar()
        distincts = connexion.execute(text("SELECT COUNT(DISTINCT uid) FROM silver_marches")).scalar()
    assert total == distincts


def test_gold_marches_ont_toutes_un_acheteur_valide():
    """Règle métier appliquée par construire_gold_marches.py : jamais de
    marché en gold sans SIRET acheteur résolu vers un acheteur existant."""
    with get_engine().begin() as connexion:
        orphelins = connexion.execute(text("""
            SELECT COUNT(*) FROM marches m
            WHERE NOT EXISTS (SELECT 1 FROM acheteurs a WHERE a.siret = m.siret_acheteur)
        """)).scalar()
    assert orphelins == 0


def test_gold_marches_respectent_le_perimetre_cpv72():
    """Depuis le 31/08/2026 : bronze/silver ne filtrent plus par CPV (import
    complet, France/3 ans, tous secteurs) — le périmètre CPV 72xxxxxx du
    sujet (section 6) est appliqué uniquement en aval, dans
    scripts/construire_gold_marches.py. Régression : aucun marché hors de
    ce périmètre ne doit jamais atteindre gold."""
    with get_engine().begin() as connexion:
        hors_perimetre = connexion.execute(text("""
            SELECT COUNT(*) FROM marches WHERE code_cpv IS NULL OR code_cpv NOT LIKE '72%'
        """)).scalar()
    assert hors_perimetre == 0


def test_silver_marches_contient_bien_du_hors_perimetre_cpv():
    """Contrepartie du test ci-dessus : silver, lui, doit rester complet
    (non filtré par CPV) — sinon le filtrage en aval n'aurait plus rien à
    filtrer et la bascule du 31/08/2026 (import complet, filtrage en gold)
    serait revenue en arrière silencieusement."""
    with get_engine().begin() as connexion:
        hors_perimetre = connexion.execute(text("""
            SELECT COUNT(*) FROM silver_marches WHERE code_cpv IS NULL OR code_cpv NOT LIKE '72%'
        """)).scalar()
    assert hors_perimetre > 0


def test_accord_cadre_multi_titulaires_preserve():
    """Régression : un marché avec plusieurs titulaires (accord-cadre à
    attributaires multiples) ne doit pas être réduit à un seul titulaire
    par la couche silver -> gold (cf. silver_attributions dans
    db/schema.sql)."""
    with get_engine().begin() as connexion:
        nb_marches_multi_titulaires = connexion.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT uid_marche FROM attributions
                GROUP BY uid_marche
                HAVING COUNT(*) > 1
            ) t
        """)).scalar()
    assert nb_marches_multi_titulaires > 0
