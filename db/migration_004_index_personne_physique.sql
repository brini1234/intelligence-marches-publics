-- migration_004_index_personne_physique.sql
-- Idempotent : peut être relancé sans risque.
-- À exécuter avec : psql "$DATABASE_URL" -f db/migration_004_index_personne_physique.sql
--
-- Nécessaire à resoudre_personne_physique() (scripts/resolution_identite.py,
-- niveau 3 étendu) : un entrepreneur individuel n'a jamais de
-- denominationUniteLegale en SIRENE (13,8M lignes du stock national dans ce
-- cas) — seuls nomUniteLegale (nom de famille) et prenom1UniteLegale sont
-- renseignés. Sans index dédié, une égalité sur nomUniteLegale scannerait
-- les 29,8M lignes du stock à chaque appel (constaté : requête de contrôle
-- sans index non terminée après plusieurs minutes sur cette machine).

CREATE INDEX IF NOT EXISTS idx_sirene_stock_unite_legale_nom
    ON sirene_stock_unite_legale ("nomUniteLegale")
    WHERE "denominationUniteLegale" IS NULL;
