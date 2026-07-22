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