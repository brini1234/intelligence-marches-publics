-- Table des entreprises, alimentée par SIRENE
CREATE TABLE entreprises (
    siren           CHAR(9) PRIMARY KEY,
    siret_siege     CHAR(14),
    denomination    TEXT NOT NULL,
    forme_juridique TEXT,
    code_naf        VARCHAR(10),
    date_creation   DATE,
    est_active      BOOLEAN DEFAULT TRUE,
    adresse         TEXT,
    code_postal     VARCHAR(10),
    commune         TEXT,
    source          TEXT DEFAULT 'SIRENE',
    date_maj        TIMESTAMP DEFAULT NOW()
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