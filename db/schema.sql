-- =====================================================================
-- Architecture bronze / silver / gold (sujet, section 6, S2 : "Ingestion
-- TED et DECP sur CPV restreint, couches bronze/silver/gold, déduplication,
-- versionnement"). Trois étages :
--
--   BRONZE  : copie brute, APPEND-ONLY, jamais écrasée. Une exécution de
--             scripts/charger_bronze_decp.py ou charger_bronze_ted.py
--             insère de nouvelles lignes ; plusieurs lignes peuvent
--             partager le même uid si le pipeline est relancé après une
--             mise à jour côté source. C'est ça, le "versionnement" :
--             aucune ligne bronze n'est jamais mise à jour ni supprimée.
--
--   SILVER  : reconstruite intégralement (TRUNCATE + repeuplement) à
--             chaque exécution de scripts/transformer_silver_marches.py,
--             à partir de la version la plus RÉCENTE de chaque uid en
--             bronze. C'est ça, la "déduplication" : une seule ligne par
--             marché, validée (SIRET à 14 chiffres exact sinon NULL,
--             jamais inventé) et normalisée dans un schéma unifié DECP/TED.
--             Détecte aussi les doublons probables entre sources (même
--             acheteur, CPV, montant proche, dates proches) et les flague
--             (doublon_probable_de) sans jamais les supprimer.
--
--   GOLD    : les tables métier ci-dessous (entreprises, etablissements,
--             acheteurs, marches, attributions) — structure inchangée par
--             cette architecture. Reconstruites par
--             scripts/construire_gold_marches.py depuis silver_marches
--             (les lignes flaguées comme doublons n'y créent pas de ligne
--             marches séparée, pour ne pas compter deux fois le même
--             marché dans les métriques de concurrence des parties
--             suivantes).
-- =====================================================================

-- BRONZE — DECP brut, une ligne par (uid, date_chargement). Colonnes en
-- TEXT : aucune validation à ce stade, c'est le rôle de silver.
CREATE TABLE bronze_decp_marches (
    id                      BIGSERIAL PRIMARY KEY,
    uid                     TEXT,
    id_marche               TEXT,
    acheteur_id             TEXT,
    acheteur_nom            TEXT,
    titulaire_id            TEXT,
    titulaire_nom           TEXT,
    objet                   TEXT,
    montant                 TEXT,
    code_cpv                TEXT,
    date_notification       TEXT,
    date_publication        TEXT,
    duree_mois              TEXT,
    duree_restante_mois     TEXT,
    modification_id         TEXT,
    date_chargement         TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_bronze_decp_marches_uid ON bronze_decp_marches(uid, date_chargement DESC);

-- BRONZE — TED brut (déjà normalisé au niveau champ par
-- connectors/ted.py::_normaliser_notice, mais pas encore validé), une
-- ligne par (publication_number, date_chargement).
CREATE TABLE bronze_ted_notices (
    id                      BIGSERIAL PRIMARY KEY,
    publication_number      TEXT,
    notice_identifier       TEXT,
    publication_date        TEXT,
    buyer_name              TEXT,
    buyer_country           TEXT,
    buyer_identifier        TEXT,
    winner_name             TEXT,
    winner_country          TEXT,
    winner_identifier       TEXT,
    code_cpv                TEXT,
    montant                 TEXT,
    objet                   TEXT,
    procedure_type          TEXT,
    date_chargement         TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_bronze_ted_notices_uid ON bronze_ted_notices(publication_number, date_chargement DESC);

-- SILVER — schéma unifié DECP/TED, une ligne par uid (la plus récente
-- version bronze, en cas de ré-exécution ; en cas de plusieurs
-- modification_id pour un même marché au sein d'un même chargement, la
-- plus élevée l'emporte), validée et normalisée. Reconstruite entièrement
-- à chaque exécution de transformer_silver_marches.py (TRUNCATE +
-- repeuplement). Uniquement les attributs de niveau MARCHÉ (acheteur,
-- objet, montant, dates, CPV) : un marché (accord-cadre notamment) peut
-- avoir plusieurs titulaires, portés séparément par silver_attributions
-- ci-dessous — les fusionner ici ferait disparaître des concurrents réels.
CREATE TABLE silver_marches (
    uid                     TEXT PRIMARY KEY,
    source                  TEXT NOT NULL,
    siret_acheteur          CHAR(14),
    nom_acheteur            TEXT,
    objet                   TEXT,
    montant                 NUMERIC,
    code_cpv                VARCHAR(20),
    date_notification       DATE,
    date_publication        DATE,
    duree_mois              NUMERIC,
    duree_restante_mois     NUMERIC,
    modification_id         INTEGER,
    doublon_probable_de     TEXT REFERENCES silver_marches(uid),
    date_transformation     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_silver_marches_acheteur ON silver_marches(siret_acheteur);
CREATE INDEX idx_silver_marches_source ON silver_marches(source);

-- SILVER — titulaires par marché (plusieurs lignes possibles par uid : un
-- accord-cadre peut avoir plusieurs attributaires, cf. commentaire
-- ci-dessus). Dédupliquée par (uid, siret_titulaire) sur l'ensemble de
-- l'historique bronze — un même couple marché/titulaire observé dans
-- plusieurs versions bronze ne compte qu'une fois. Uniquement les SIRET
-- valides à 14 chiffres : jamais un identifiant inventé, une ligne sans
-- titulaire résolvable n'a simplement rien à apporter ici.
CREATE TABLE silver_attributions (
    uid                     TEXT NOT NULL REFERENCES silver_marches(uid),
    siret_titulaire         CHAR(14) NOT NULL,
    nom_titulaire           TEXT,
    source                  TEXT NOT NULL,
    date_transformation     TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (uid, siret_titulaire)
);

-- =====================================================================
-- GOLD — tables métier, inchangées par l'architecture bronze/silver/gold.
-- =====================================================================

-- Table des entreprises, alimentée par SIRENE
CREATE TABLE entreprises (
    siren                  CHAR(9) PRIMARY KEY,
    siret_siege            CHAR(14),
    denomination           TEXT NOT NULL,
    raison_sociale_legale  TEXT,
    forme_juridique        TEXT,
    code_naf               VARCHAR(10),
    date_creation          DATE,
    est_active             BOOLEAN DEFAULT TRUE,
    etat_administratif     TEXT,
    est_siege              BOOLEAN,
    adresse                TEXT,
    code_postal            VARCHAR(10),
    commune                TEXT,
    source                 TEXT DEFAULT 'SIRENE',
    date_maj               TIMESTAMP DEFAULT NOW()
);

-- Table des établissements (un SIREN peut avoir plusieurs SIRET)
CREATE TABLE etablissements (
    siret           CHAR(14) PRIMARY KEY,
    siren           CHAR(9) REFERENCES entreprises(siren),
    est_siege       BOOLEAN,
    adresse         TEXT,
    code_postal     VARCHAR(10),
    commune         TEXT,
    date_maj        TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_etablissements_siren ON etablissements(siren);
CREATE INDEX idx_entreprises_denomination ON entreprises USING gin (to_tsvector('french', denomination));

-- Table des acheteurs publics
CREATE TABLE acheteurs (
    siret           CHAR(14) PRIMARY KEY,
    nom             TEXT NOT NULL,
    date_maj        TIMESTAMP DEFAULT NOW()
);

-- Table des marchés (un objet de marché = une ligne, indépendamment du/des titulaire(s))
CREATE TABLE marches (
    uid                     TEXT PRIMARY KEY,
    id_marche               TEXT,
    siret_acheteur          CHAR(14) REFERENCES acheteurs(siret),
    objet                   TEXT,
    montant                 NUMERIC,
    duree_mois              NUMERIC,
    duree_restante_mois     NUMERIC,
    code_cpv                VARCHAR(20),
    date_notification       DATE,
    date_publication        DATE,
    procedure_type          TEXT,
    forme_prix              TEXT,
    modification_id         INTEGER DEFAULT 0,
    donnees_actuelles       BOOLEAN DEFAULT TRUE,
    source                  TEXT DEFAULT 'DECP',
    date_maj                TIMESTAMP DEFAULT NOW()
);

-- Table des attributions : qui a remporté quel marché (plusieurs titulaires possibles par marché)
CREATE TABLE attributions (
    id              SERIAL PRIMARY KEY,
    uid_marche      TEXT REFERENCES marches(uid),
    siret_titulaire CHAR(14),
    siren_titulaire CHAR(9) REFERENCES entreprises(siren),
    date_maj        TIMESTAMP DEFAULT NOW(),
    UNIQUE (uid_marche, siret_titulaire)
);

CREATE INDEX idx_marches_acheteur ON marches(siret_acheteur);
CREATE INDEX idx_marches_cpv ON marches(code_cpv);
CREATE INDEX idx_marches_date_notif ON marches(date_notification);
CREATE INDEX idx_attributions_siren ON attributions(siren_titulaire);
CREATE INDEX idx_attributions_marche ON attributions(uid_marche);

-- Tables de référentiel SIRENE (national, toutes entreprises — section 3 du
-- sujet), volontairement absentes des CREATE TABLE ci-dessus :
-- sirene_stock_unite_legale et sirene_stock_etablissement sont créées et
-- peuplées par scripts/importer_stock_sirene_national.py, avec des colonnes
-- TEXT dérivées automatiquement de l'en-tête des fichiers stock INSEE au
-- moment de l'import (pas codées en dur ici) — pour que le pipeline survive
-- si l'INSEE change son dessin de fichier, plutôt que de planter ou
-- d'importer des colonnes décalées silencieusement.
--
-- Colonnes constatées (stock INSEE, à la date de cette note) :
--   sirene_stock_unite_legale   : siren, statutDiffusionUniteLegale,
--     unitePurgeeUniteLegale, dateCreationUniteLegale, sigleUniteLegale,
--     sexeUniteLegale, prenom1-4UniteLegale, prenomUsuelUniteLegale,
--     pseudonymeUniteLegale, identifiantAssociationUniteLegale,
--     trancheEffectifsUniteLegale, anneeEffectifsUniteLegale,
--     dateDernierTraitementUniteLegale, nombrePeriodesUniteLegale,
--     categorieEntreprise, anneeCategorieEntreprise, dateDebut,
--     etatAdministratifUniteLegale, nomUniteLegale, nomUsageUniteLegale,
--     denominationUniteLegale, denominationUsuelle1-3UniteLegale,
--     categorieJuridiqueUniteLegale, activitePrincipaleUniteLegale,
--     nomenclatureActivitePrincipaleUniteLegale, nicSiegeUniteLegale,
--     economieSocialeSolidaireUniteLegale, societeMissionUniteLegale,
--     caractereEmployeurUniteLegale, activitePrincipaleNAF25UniteLegale
--   sirene_stock_etablissement  : siren, nic, siret,
--     statutDiffusionEtablissement, dateCreationEtablissement,
--     trancheEffectifsEtablissement, anneeEffectifsEtablissement,
--     activitePrincipaleRegistreMetiersEtablissement,
--     dateDernierTraitementEtablissement, etablissementSiege,
--     nombrePeriodesEtablissement, complementAdresseEtablissement,
--     numeroVoieEtablissement, indiceRepetitionEtablissement,
--     dernierNumeroVoieEtablissement,
--     indiceRepetitionDernierNumeroVoieEtablissement, typeVoieEtablissement,
--     libelleVoieEtablissement, codePostalEtablissement,
--     libelleCommuneEtablissement, libelleCommuneEtrangerEtablissement,
--     distributionSpecialeEtablissement, codeCommuneEtablissement,
--     codeCedexEtablissement, libelleCedexEtablissement,
--     codePaysEtrangerEtablissement, libellePaysEtrangerEtablissement,
--     identifiantAdresseEtablissement, coordonneeLambertAbscisseEtablissement,
--     coordonneeLambertOrdonneeEtablissement, complementAdresse2Etablissement,
--     numeroVoie2Etablissement, indiceRepetition2Etablissement,
--     typeVoie2Etablissement, libelleVoie2Etablissement, codePostal2Etablissement,
--     libelleCommune2Etablissement, libelleCommuneEtranger2Etablissement,
--     distributionSpeciale2Etablissement, codeCommune2Etablissement,
--     codeCedex2Etablissement, libelleCedex2Etablissement,
--     codePaysEtranger2Etablissement, libellePaysEtranger2Etablissement,
--     dateDebut, etatAdministratifEtablissement, enseigne1-3Etablissement,
--     denominationUsuelleEtablissement, activitePrincipaleEtablissement,
--     nomenclatureActivitePrincipaleEtablissement, caractereEmployeurEtablissement,
--     activitePrincipaleNAF25Etablissement
--
-- Index créés par le script après chargement : idx_sirene_stock_unite_legale_siren,
-- idx_sirene_stock_etablissement_siren, idx_sirene_stock_etablissement_siret,
-- puis uniq_sirene_stock_unite_legale_siren / uniq_sirene_stock_etablissement_siret
-- par scripts/nettoyer_stock_sirene.py après dédoublonnage.