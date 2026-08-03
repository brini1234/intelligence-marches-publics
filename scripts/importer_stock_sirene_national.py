"""
Import COMPLET et NATIONAL des fichiers stock SIRENE (StockUniteLegale +
StockEtablissement), soit environ 30M + 40M lignes.

Différence fondamentale avec un import "ligne à ligne" : à cette échelle,
INSERT/UPDATE via SQLAlchemy executemany prendrait des heures, voire ne
terminerait jamais de façon fiable. On utilise donc la commande COPY native
de PostgreSQL, qui charge le fichier en un seul flux continu, directement
depuis le CSV vers la table — c'est la seule méthode qui soit à la fois
complète (aucune ligne écartée) et automatique (aucune sélection, aucune
boucle Python sur les lignes).

Étapes :
    1. Décompresser les deux zips (une fois)
    2. Lire uniquement l'en-tête de chaque CSV pour connaître les colonnes
       réelles (on ne les code pas en dur : si l'INSEE change son dessin de
       fichier, la table s'adapte automatiquement plutôt que de planter ou,
       pire, d'importer des colonnes décalées silencieusement)
    3. (Re)créer une table miroir avec ces colonnes en TEXT
    4. COPY du CSV entier dans la table, en un seul flux
    5. Indexer siren / siret une fois les données chargées (plus rapide
       qu'indexer avant, car l'index n'a pas à être mis à jour à chaque ligne)

Prérequis : les deux zips doivent être dans data/sirene/
    - stock_unite_legale.zip   (dénomination, forme juridique, NAF...)
    - stock_etablissement.zip  (adresse, SIRET, établissement siège...)

Attention : ~15-25 Go une fois décompressé + indexé. Prévoir de la place
disque et compter plusieurs dizaines de minutes selon la machine.

Usage :
    python scripts/importer_stock_sirene_national.py
"""
import csv
import os
import sys
import time
import zipfile

sys.path.append(".")

from db.connection import get_engine

DATA_DIR = "data/sirene"

FICHIERS = [
    {
        "zip": os.path.join(DATA_DIR, "stock_unite_legale.zip"),
        "table": "sirene_stock_unite_legale",
        "colonnes_index": ["siren"],
    },
    {
        "zip": os.path.join(DATA_DIR, "stock_etablissement.zip"),
        "table": "sirene_stock_etablissement",
        "colonnes_index": ["siren", "siret"],
    },
]


def _extraire_csv(chemin_zip: str) -> str:
    if not os.path.exists(chemin_zip):
        raise FileNotFoundError(
            f"Fichier introuvable : {chemin_zip}. "
            "Télécharge-le depuis l'onglet Fichiers du jeu de données Sirene sur data.gouv.fr."
        )
    dossier = os.path.dirname(chemin_zip)
    with zipfile.ZipFile(chemin_zip) as archive:
        noms_csv = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if len(noms_csv) != 1:
            raise RuntimeError(f"Attendu 1 CSV dans {chemin_zip}, trouvé {len(noms_csv)} : {noms_csv}")
        chemin_csv = os.path.join(dossier, noms_csv[0])
        if not os.path.exists(chemin_csv):
            print(f"  Décompression de {os.path.basename(chemin_zip)} ...")
            archive.extract(noms_csv[0], dossier)
    return chemin_csv


def _lire_entete(chemin_csv: str) -> list[str]:
    with open(chemin_csv, "r", encoding="utf-8", newline="") as f:
        return next(csv.reader(f))


def _creer_table(connexion_brute, table: str, colonnes: list[str]) -> None:
    curseur = connexion_brute.cursor()
    curseur.execute(f'DROP TABLE IF EXISTS "{table}"')
    definitions = ", ".join(f'"{c}" TEXT' for c in colonnes)
    # UNLOGGED : pas de journal de transactions -> chargement bien plus rapide.
    # Acceptable ici car cette table est un cache reconstruit à chaque import,
    # pas une donnée métier qu'on ne peut pas se permettre de perdre.
    curseur.execute(f'CREATE UNLOGGED TABLE "{table}" ({definitions})')
    connexion_brute.commit()
    curseur.close()


def _copier_csv(connexion_brute, table: str, chemin_csv: str) -> int:
    curseur = connexion_brute.cursor()
    with open(chemin_csv, "r", encoding="utf-8", newline="") as f:
        curseur.copy_expert(
            f'COPY "{table}" FROM STDIN WITH (FORMAT csv, HEADER true)', f
        )
    connexion_brute.commit()
    curseur.execute(f'SELECT COUNT(*) FROM "{table}"')
    nb_lignes = curseur.fetchone()[0]
    curseur.close()
    return nb_lignes


def _indexer(connexion_brute, table: str, colonnes_index: list[str]) -> None:
    curseur = connexion_brute.cursor()
    for colonne in colonnes_index:
        nom_index = f"idx_{table}_{colonne}"
        print(f"  Indexation {table}.{colonne} ...")
        curseur.execute(f'CREATE INDEX IF NOT EXISTS "{nom_index}" ON "{table}" ("{colonne}")')
    connexion_brute.commit()
    curseur.close()


def importer_stock_sirene_national():
    engine = get_engine()
    connexion_brute = engine.raw_connection()

    try:
        for fichier in FICHIERS:
            debut = time.time()
            table = fichier["table"]
            print(f"\n=== {table} ===")

            chemin_csv = _extraire_csv(fichier["zip"])

            colonnes = _lire_entete(chemin_csv)
            print(f"  {len(colonnes)} colonnes détectées dans le fichier source")

            _creer_table(connexion_brute, table, colonnes)

            print(f"  Chargement COPY en cours (peut prendre plusieurs minutes) ...")
            nb_lignes = _copier_csv(connexion_brute, table, chemin_csv)
            print(f"  {nb_lignes:,} lignes chargées".replace(",", " "))

            _indexer(connexion_brute, table, fichier["colonnes_index"])

            duree = time.time() - debut
            print(f"  Terminé en {duree:.0f}s")
    finally:
        connexion_brute.close()

    print("\n✅ Import national SIRENE complet. Prochaine étape : "
          "python scripts/enrichir_entreprises_depuis_sirene.py")


if __name__ == "__main__":
    importer_stock_sirene_national()
