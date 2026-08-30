"""
Nettoie les tables brutes chargées par importer_stock_sirene_national.py.

Un COPY charge les données telles quelles : chaînes vides au lieu de NULL,
espaces parasites, doublons possibles si le script a été relancé
partiellement. Cette étape corrige tout ça AVANT que enrichir_entreprises_
depuis_sirene.py ne s'appuie dessus — sinon les '' se propagent silencieusement
dans `entreprises` (ex: forme_juridique = '' au lieu de NULL, ce qui casse
les tests "IS NOT NULL" de couverture).

Chaque table est nettoyée en 1 seul UPDATE (toutes les colonnes en même temps,
pas une passe par colonne) pour rester rapide sur 30-40M lignes.

Usage :
    python scripts/nettoyer_stock_sirene.py
"""
import sys
sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine

TABLES = {
    "sirene_stock_unite_legale": {"cle": "siren", "regex_cle": r"^\d{9}$"},
    "sirene_stock_etablissement": {"cle": "siret", "regex_cle": r"^\d{14}$"},
}


def _lister_colonnes(connexion, table: str) -> list[str]:
    lignes = connexion.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = :table ORDER BY ordinal_position
    """), {"table": table}).fetchall()
    return [r[0] for r in lignes]


def _normaliser_vides_en_null(connexion, table: str, colonnes: list[str]) -> None:
    """Une seule UPDATE qui traite toutes les colonnes texte à la fois."""
    assignations = ", ".join(f'"{c}" = NULLIF(TRIM("{c}"), \'\')' for c in colonnes)
    connexion.execute(text(f'UPDATE "{table}" SET {assignations}'))


def _supprimer_doublons(connexion, table: str, cle: str) -> int:
    resultat = connexion.execute(text(f"""
        DELETE FROM "{table}" a
        USING "{table}" b
        WHERE a.ctid < b.ctid AND a."{cle}" = b."{cle}"
    """))
    return resultat.rowcount


def _compter_cles_invalides(connexion, table: str, cle: str, regex: str) -> int:
    return connexion.execute(text(
        f'SELECT COUNT(*) FROM "{table}" WHERE "{cle}" IS NULL OR "{cle}" !~ :regex'
    ), {"regex": regex}).scalar()


def nettoyer_stock_sirene():
    engine = get_engine()

    for table, regles in TABLES.items():
        print(f"\n=== Nettoyage {table} ===")
        with engine.begin() as connexion:
            nb_avant = connexion.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
            print(f"  Lignes avant nettoyage : {nb_avant:,}".replace(",", " "))

            colonnes = _lister_colonnes(connexion, table)
            print(f"  Normalisation '' -> NULL sur {len(colonnes)} colonnes ...")
            _normaliser_vides_en_null(connexion, table, colonnes)

            print(f"  Suppression des doublons sur \"{regles['cle']}\" ...")
            nb_doublons = _supprimer_doublons(connexion, table, regles["cle"])
            print(f"  {nb_doublons} doublon(s) supprimé(s)")

            nb_cles_invalides = _compter_cles_invalides(connexion, table, regles["cle"], regles["regex_cle"])
            print(f"  Clés \"{regles['cle']}\" invalides ou manquantes : {nb_cles_invalides} "
                  f"(non supprimées, seulement signalées)")

            cle = regles["cle"]
            connexion.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS "uniq_{table}_{cle}" '
                                    f'ON "{table}" ("{cle}")'))

            # UNLOGGED -> LOGGED : maintenant que les données sont propres, on les
            # rend durables (résistantes à un crash Postgres), au prix d'un léger
            # ralentissement d'écriture qu'on n'utilise plus à ce stade.
            connexion.execute(text(f'ALTER TABLE "{table}" SET LOGGED'))

            nb_apres = connexion.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
            print(f"  Lignes après nettoyage : {nb_apres:,}".replace(",", " "))

    with engine.begin() as connexion:
        # Index trigram : nécessaire au rapprochement flou (niveau 3 de la
        # résolution d'identité, scripts/resolution_identite.py). Créé ici
        # (pas en commande manuelle) pour que le pipeline reste rejouable
        # de zéro à partir du seul README.
        print("\n=== Index trigram pour le rapprochement flou (pg_trgm) ===")
        connexion.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
        connexion.execute(text(
            'CREATE INDEX IF NOT EXISTS idx_sirene_stock_unite_legale_denom_trgm '
            'ON sirene_stock_unite_legale USING gin ("denominationUniteLegale" gin_trgm_ops)'
        ))
        print("  Index créé (ou déjà présent).")

        # Index sur nomUniteLegale, restreint aux entrepreneurs individuels
        # (denominationUniteLegale IS NULL, 13,8M lignes du stock national) :
        # nécessaire à resoudre_personne_physique() (résolution d'identité
        # niveau 3 étendu) — un entrepreneur individuel n'a jamais de
        # dénomination, seuls nomUniteLegale/prenom1UniteLegale existent.
        print("=== Index pour la résolution des personnes physiques (entrepreneurs individuels) ===")
        connexion.execute(text(
            'CREATE INDEX IF NOT EXISTS idx_sirene_stock_unite_legale_nom '
            'ON sirene_stock_unite_legale ("nomUniteLegale") '
            'WHERE "denominationUniteLegale" IS NULL'
        ))
        print("  Index créé (ou déjà présent).")

    print("\n✅ Nettoyage terminé. Prochaine étape : "
          "python scripts/enrichir_entreprises_depuis_sirene.py")


if __name__ == "__main__":
    nettoyer_stock_sirene()
