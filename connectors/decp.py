import os
from datetime import date

import duckdb
import requests

# URL stable : redirige automatiquement vers le fichier Parquet du jour.
# Ne JAMAIS coder en dur l'URL datée (elle change chaque jour et finit en 404).
PARQUET_URL = "https://www.data.gouv.fr/api/1/datasets/r/11cea8e8-df3e-4ed1-932b-781e2635e432"
PARQUET_LOCAL_PATH = "data/decp/decp.parquet"


def _download_parquet_if_needed(force: bool = False) -> str:
    """Télécharge le fichier Parquet consolidé complet (~235 Mo), une seule fois."""
    if os.path.exists(PARQUET_LOCAL_PATH) and not force:
        return PARQUET_LOCAL_PATH

    os.makedirs(os.path.dirname(PARQUET_LOCAL_PATH), exist_ok=True)
    print(f"Téléchargement du fichier Parquet DECP (~235 Mo) vers {PARQUET_LOCAL_PATH} ...")
    response = requests.get(PARQUET_URL, stream=True, timeout=600)
    response.raise_for_status()
    with open(PARQUET_LOCAL_PATH, "wb") as handle:
        for chunk in response.iter_content(1024 * 1024):
            if chunk:
                handle.write(chunk)
    print("Téléchargement terminé.")
    return PARQUET_LOCAL_PATH


def _load_parquet_rows(siret_acheteur: str | None = None, prefixe_cpv: str | None = None) -> list[dict]:
    """
    Charge, filtre et retourne les lignes DECP du périmètre demandé,
    directement depuis le Parquet via DuckDB (pas d'appel API paginé).
    """
    parquet_path = _download_parquet_if_needed()

    where_clauses = ["1=1"]
    params = []
    if prefixe_cpv:
        where_clauses.append("codeCPV LIKE ?")
        params.append(f"{prefixe_cpv}%")
    if siret_acheteur:
        where_clauses.append("acheteur_id = ?")
        params.append(siret_acheteur)

    query = f"""
        SELECT
            uid, id, acheteur_id, acheteur_nom,
            titulaire_id, titulaire_nom, objet, montant,
            codeCPV, dateNotification, datePublicationDonnees,
            dureeMois, dureeRestanteMois, donneesActuelles, modification_id
        FROM read_parquet(?)
        WHERE {' AND '.join(where_clauses)}
    """
    with duckdb.connect() as conn:
        rows = conn.execute(query, [parquet_path] + params).fetchall()

    colonnes = [
        "uid", "id", "acheteur_id", "acheteur_nom",
        "titulaire_id", "titulaire_nom", "objet", "montant",
        "codeCPV", "dateNotification", "datePublicationDonnees",
        "dureeMois", "dureeRestanteMois", "donneesActuelles", "modification_id",
    ]
    return [dict(zip(colonnes, row)) for row in rows]


def rechercher_marches_par_acheteur(siret_acheteur: str, limite: int = 50) -> list[dict]:
    """Récupère les marchés d'un acheteur précis, à partir du Parquet consolidé."""
    marches = _load_parquet_rows(siret_acheteur=siret_acheteur)
    return marches[:limite]


def exporter_perimetre_complet_csv(
    prefixe_cpv: str | None = None,
    chemin_sortie: str = "data/decp/perimetre_complet.csv",
) -> tuple[str, int]:
    """
    Exporte les marchés France/3 ans directement en CSV via DuckDB, prêt
    pour un COPY PostgreSQL. Le filtrage se fait entièrement en SQL DuckDB
    — aucune boucle Python sur des millions de lignes, contrairement à un
    import ligne à ligne qui ne terminerait pas en un temps raisonnable à
    cette échelle (cf. scripts/importer_stock_sirene_national.py, même
    principe).

    prefixe_cpv=None (par défaut, depuis le 31/08/2026) : PAS de filtre CPV
    à l'export — la totalité du périmètre France/3 ans, tous secteurs
    (~1,15M lignes), est chargée dans bronze_decp_marches. Le sujet
    documente lui-même que les codes CPV sont "saisis approximativement"
    côté DECP (section 3) : filtrer par CPV *avant* le chargement écarterait
    définitivement, sans trace ni possibilité de rattrapage, tout marché
    réellement en périmètre mais mal étiqueté à la source — contraire au
    principe du projet de ne jamais fausser une jointure ni masquer un trou.
    Le périmètre CPV 72xxxxxx proposé par le sujet (section 6, "services
    informatiques") reste appliqué, mais en aval, comme règle métier
    explicite et auditable dans scripts/construire_gold_marches.py — jamais
    à l'import. Passer prefixe_cpv="72" reste possible (ancien comportement,
    utile pour un export ponctuel restreint) mais n'est plus le défaut.
    """
    parquet_path = _download_parquet_if_needed()
    today = date.today()
    date_min = date(today.year - 3, today.month, today.day)

    where_clauses = [
        "donneesActuelles = true",
        "CAST(datePublicationDonnees AS DATE) >= ?",
    ]
    params = [str(date_min)]
    if prefixe_cpv:
        where_clauses.append("codeCPV LIKE ?")
        params.append(f"{prefixe_cpv}%")

    os.makedirs(os.path.dirname(chemin_sortie), exist_ok=True)
    where_sql = " AND ".join(where_clauses)
    # Compté via DuckDB, pas par un décompte de lignes du CSV en Python :
    # certains champs texte (ex. "objet") contiennent des retours à la ligne
    # à l'intérieur d'un champ entre guillemets, ce qui fausserait un simple
    # comptage de sauts de ligne du fichier.
    count_query = f"SELECT COUNT(*) FROM read_parquet(?) WHERE {where_sql}"
    copy_query = f"""
        COPY (
            SELECT
                uid, id, acheteur_id, acheteur_nom,
                titulaire_id, titulaire_nom, objet, montant,
                codeCPV, dateNotification, datePublicationDonnees,
                dureeMois, dureeRestanteMois, modification_id
            FROM read_parquet(?)
            WHERE {where_sql}
        ) TO '{chemin_sortie}' (FORMAT csv, HEADER true)
    """
    with duckdb.connect() as conn:
        nb_lignes = conn.execute(count_query, [parquet_path] + params).fetchone()[0]
        conn.execute(copy_query, [parquet_path] + params)

    return chemin_sortie, nb_lignes


if __name__ == "__main__":
    # Ceci est un simple test de connexion au fichier Parquet, PAS un import.
    # L'import réel et complet du périmètre se fait via :
    # scripts/importer_perimetre_complet.py -> exporter_perimetre_complet_csv()
    marches = rechercher_marches_par_acheteur("43276694700019")
    print(f"{len(marches)} marché(s) récupéré(s)")
    for m in marches[:3]:
        print(m)