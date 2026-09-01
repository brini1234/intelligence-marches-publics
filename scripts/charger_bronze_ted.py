"""
Chargement de la couche BRONZE TED (sujet, section 6, S2 : couches
bronze/silver/gold). Depuis le 31/08/2026 : bronze est une copie brute
COMPLÈTE (France, fenêtre de 3 ans, tous secteurs, ~7 900 avis) — plus de
filtre CPV à l'import (cf. connectors/ted.py::exporter_perimetre_complet).
Le périmètre CPV 72xxxxxx du sujet (section 6) est appliqué en aval, comme
règle métier explicite dans scripts/construire_gold_marches.py.

Ce script ne fait QUE charger le brut dans bronze_ted_notices (APPEND-ONLY,
jamais d'UPDATE ni de DELETE — c'est le "versionnement" : relancer ce
script après une mise à jour côté source ajoute de nouvelles lignes plutôt
que d'écraser les précédentes). Il ne touche plus aux tables métier : c'est
le rôle de scripts/transformer_silver_marches.py (déduplication, validation
des SIRET — jamais un SIRET inventé si absent) puis
scripts/construire_gold_marches.py (tables métier).

Volume TED France/3 ans, tous secteurs : ~7 900 avis (contre ~330 avec
l'ancien filtre CPV72 en dur, vérifié le 31/08/2026) — insertion SQL
directe, pas de COPY/staging nécessaire contrairement à DECP (~1,15M
lignes).

Usage :
    python scripts/charger_bronze_ted.py
"""
import sys

sys.path.append(".")

from sqlalchemy import text

from connectors.ted import exporter_perimetre_complet
from db.connection import get_engine


def charger_bronze_ted():
    engine = get_engine()

    print("Récupération des avis d'attribution TED (API, pagination complète) ...")
    notices = exporter_perimetre_complet()
    print(f"  {len(notices)} avis récupéré(s)")

    with engine.begin() as connexion:
        print("Insertion dans bronze_ted_notices (append, jamais d'écrasement) ...")
        for notice in notices:
            # bronze est intégralement en TEXT (donnée brute) ; "montant" est
            # le seul champ non-string renvoyé par connectors/ted.py.
            notice = {**notice, "montant": str(notice["montant"]) if notice["montant"] is not None else None}
            connexion.execute(text("""
                INSERT INTO bronze_ted_notices (
                    publication_number, notice_identifier, publication_date,
                    buyer_name, buyer_country, buyer_identifier,
                    winner_name, winner_country, winner_identifier,
                    code_cpv, montant, objet, procedure_type
                )
                VALUES (
                    :publication_number, :notice_identifier, :publication_date,
                    :buyer_name, :buyer_country, :buyer_identifier,
                    :winner_name, :winner_country, :winner_identifier,
                    :code_cpv, :montant, :objet, :procedure_type
                )
            """), notice)

        nb_bronze_total = connexion.execute(text(
            "SELECT COUNT(*) FROM bronze_ted_notices"
        )).scalar()
        nb_uid_distincts = connexion.execute(text(
            "SELECT COUNT(DISTINCT publication_number) FROM bronze_ted_notices"
        )).scalar()

    print(f"\n✅ Chargement bronze TED terminé. {len(notices)} avis ajouté(s) cette exécution.")
    print(f"  bronze_ted_notices : {nb_bronze_total} ligne(s) au total, "
          f"{nb_uid_distincts} avis distinct(s) (l'écart = historique de versions)")


if __name__ == "__main__":
    charger_bronze_ted()
