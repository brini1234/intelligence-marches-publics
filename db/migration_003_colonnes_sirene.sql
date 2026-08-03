-- migration_003_colonnes_sirene.sql
-- Idempotent : peut être relancé sans risque, même si certaines colonnes existent déjà.
-- À exécuter avec : psql "$DATABASE_URL" -f db/migration_003_colonnes_sirene.sql

ALTER TABLE entreprises ADD COLUMN IF NOT EXISTS raison_sociale_legale TEXT;
ALTER TABLE entreprises ADD COLUMN IF NOT EXISTS forme_juridique TEXT;
ALTER TABLE entreprises ADD COLUMN IF NOT EXISTS code_naf TEXT;
ALTER TABLE entreprises ADD COLUMN IF NOT EXISTS date_creation DATE;
ALTER TABLE entreprises ADD COLUMN IF NOT EXISTS etat_administratif TEXT;
ALTER TABLE entreprises ADD COLUMN IF NOT EXISTS est_siege BOOLEAN;
ALTER TABLE entreprises ADD COLUMN IF NOT EXISTS adresse TEXT;
ALTER TABLE entreprises ADD COLUMN IF NOT EXISTS code_postal TEXT;
ALTER TABLE entreprises ADD COLUMN IF NOT EXISTS commune TEXT;
ALTER TABLE entreprises ADD COLUMN IF NOT EXISTS siret_siege TEXT;

-- Vérification : liste les colonnes de la table après migration.
-- Doit afficher toutes celles ci-dessus en plus des colonnes déjà existantes
-- (siren, denomination, est_active...).
\d entreprises
