-- migration_005_index_cpv_silver.sql
-- Idempotent : peut être relancé sans risque.
-- À exécuter avec : psql "$DATABASE_URL" -f db/migration_005_index_cpv_silver.sql
--
-- Nécessaire depuis le 31/08/2026 : bronze/silver ne filtrent plus par CPV
-- à l'import (cf. README, section "Pipeline de données") — silver_marches
-- passe de ~29K à ~1,15M lignes. Le périmètre CPV 72xxxxxx du sujet
-- (section 6) est désormais appliqué comme filtre SQL explicite dans
-- scripts/construire_gold_marches.py (WHERE code_cpv LIKE '72%'), à cette
-- échelle un scan complet sans index ne serait plus acceptable. Index de
-- motif (varchar_pattern_ops) plutôt qu'un btree standard : nécessaire pour
-- qu'un LIKE 'prefixe%' utilise l'index quel que soit le collationnement de
-- la base (un btree standard ne le garantit que sous collation "C").

CREATE INDEX IF NOT EXISTS idx_silver_marches_cpv_pattern
    ON silver_marches (code_cpv varchar_pattern_ops);
