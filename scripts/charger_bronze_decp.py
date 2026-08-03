"""
Chargement de la couche BRONZE DECP (sujet, section 6, S2 : couches
bronze/silver/gold). Périmètre conforme au sujet : CPV 72xxxxxx, France,
historique de 3 à 5 ans (section 6). Le filtrage se fait uniquement par
périmètre (préfixe CPV, fenêtre temporelle), jamais par choix manuel d'un
acheteur en particulier.

Ce script ne fait QUE charger le brut dans bronze_decp_marches (APPEND-ONLY,
jamais d'UPDATE ni de DELETE — c'est le "versionnement" : relancer ce script
après une mise à jour côté source ajoute de nouvelles lignes plutôt que
d'écraser les précédentes). Il ne touche plus aux tables métier : c'est le
rôle de scripts/transformer_silver_marches.py (déduplication, validation)
puis scripts/construire_gold_marches.py (tables métier).

Même principe que importer_stock_sirene_national.py : à l'échelle du
périmètre complet, un import ligne à ligne via SQLAlchemy ne termine pas
dans un temps raisonnable. On exporte donc le périmètre filtré en CSV via
DuckDB (connectors/decp.py::exporter_perimetre_complet_csv), on le charge
dans une table de passage éphémère via COPY, puis on l'insère dans
bronze_decp_marches par une requête ensembliste — aucune boucle Python.

Usage :
    python scripts/charger_bronze_decp.py
"""
import sys
sys.path.append(".")

from sqlalchemy import text

from connectors.decp import exporter_perimetre_complet_csv
from db.connection import get_engine

COLONNES_STAGE = [
    "uid", "id", "acheteur_id", "acheteur_nom",
    "titulaire_id", "titulaire_nom", "objet", "montant",
    "codeCPV", "dateNotification", "datePublicationDonnees",
    "dureeMois", "dureeRestanteMois", "modification_id",
]


def _creer_table_stage(connexion_brute) -> None:
    curseur = connexion_brute.cursor()
    curseur.execute("DROP TABLE IF EXISTS decp_stage_batch")
    definitions = ", ".join(f'"{c}" TEXT' for c in COLONNES_STAGE)
    # UNLOGGED : table de passage strictement transitoire pour le COPY,
    # supprimée en fin d'exécution. bronze_decp_marches (LOGGED, append-only)
    # est la véritable copie brute persistée — cette table-ci n'est qu'un
    # tampon technique.
    curseur.execute(f"CREATE UNLOGGED TABLE decp_stage_batch ({definitions})")
    connexion_brute.commit()
    curseur.close()


def _copier_csv(connexion_brute, chemin_csv: str) -> int:
    curseur = connexion_brute.cursor()
    with open(chemin_csv, "r", encoding="utf-8", newline="") as f:
        curseur.copy_expert(
            "COPY decp_stage_batch FROM STDIN WITH (FORMAT csv, HEADER true)", f
        )
    connexion_brute.commit()
    curseur.execute("SELECT COUNT(*) FROM decp_stage_batch")
    nb_lignes = curseur.fetchone()[0]
    curseur.close()
    return nb_lignes


def charger_bronze_decp(prefixe_cpv: str | None = "72"):
    engine = get_engine()

    print("Export du périmètre depuis le Parquet DECP (DuckDB) ...")
    chemin_csv, nb_exportees = exporter_perimetre_complet_csv(prefixe_cpv=prefixe_cpv)
    print(f"  {nb_exportees:,} ligne(s) exportée(s) vers {chemin_csv}".replace(",", " "))

    connexion_brute = engine.raw_connection()
    try:
        print("Chargement dans la table de passage transitoire ...")
        _creer_table_stage(connexion_brute)
        nb_stage = _copier_csv(connexion_brute, chemin_csv)
        print(f"  {nb_stage:,} ligne(s) en table de passage".replace(",", " "))
    finally:
        connexion_brute.close()

    with engine.begin() as connexion:
        print("Insertion dans bronze_decp_marches (append, jamais d'écrasement) ...")
        connexion.execute(text("""
            INSERT INTO bronze_decp_marches (
                uid, id_marche, acheteur_id, acheteur_nom,
                titulaire_id, titulaire_nom, objet, montant, code_cpv,
                date_notification, date_publication,
                duree_mois, duree_restante_mois, modification_id
            )
            SELECT
                uid, id, acheteur_id, acheteur_nom,
                titulaire_id, titulaire_nom, objet, montant, "codeCPV",
                "dateNotification", "datePublicationDonnees",
                "dureeMois", "dureeRestanteMois", modification_id
            FROM decp_stage_batch
        """))
        nb_bronze_total = connexion.execute(text(
            "SELECT COUNT(*) FROM bronze_decp_marches"
        )).scalar()
        nb_uid_distincts = connexion.execute(text(
            "SELECT COUNT(DISTINCT uid) FROM bronze_decp_marches"
        )).scalar()

    with engine.begin() as connexion:
        connexion.execute(text("DROP TABLE IF EXISTS decp_stage_batch"))

    print(f"\n✅ Chargement bronze DECP terminé. "
          f"{nb_stage:,} ligne(s) ajoutée(s) cette exécution.".replace(",", " "))
    print(f"  bronze_decp_marches : {nb_bronze_total:,} ligne(s) au total, "
          f"{nb_uid_distincts:,} uid distinct(s) (l'écart = historique de versions)".replace(",", " "))


if __name__ == "__main__":
    charger_bronze_decp()
