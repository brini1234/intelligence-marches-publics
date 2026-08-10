# Rapport de stage — Intelligence concurrentielle sur les marchés publics

**Périmètre couvert par ce rapport :** S1 à S5, S7, et la partie de S8 réellement construite (bloc de décision, harnais d'évaluation). S6 (agents) et la passerelle LLM sont hors périmètre de cette livraison — documentés en section 8 (Pistes d'extension), pas construits.

**Date de rédaction :** 10/08/2026. Tous les chiffres de ce rapport ont été obtenus en relançant les commandes citées à cette date, sur l'état actuel du dépôt et de la base ; chaque chiffre est accompagné de la commande qui permet de le revérifier.

---

## 1. Contexte et objectif

Une équipe achats/veille concurrentielle qui répond à un marché public informatique manque aujourd'hui d'un moyen rapide de savoir : qui détient probablement le marché en cours, qui sont les concurrents habituels de cet acheteur sur ce type de prestation, et à quel niveau de prix ces marchés se sont historiquement conclus. Ces informations existent dans les données publiques (DECP, TED, SIRENE) mais sont dispersées, hétérogènes dans leurs identifiants, et jamais consolidées automatiquement.

L'objectif de ce stage est de construire un pipeline qui transforme ces sources publiques en un **bloc de décision court, sourcé et honnête sur ce qu'il ne sait pas** — plutôt qu'un texte qui a l'air complet mais invente ou masque ses trous. Le périmètre retenu est celui des services informatiques (CPV 72xxxxxx) en France, sur une fenêtre de données de 3 ans, avec un référentiel d'entreprises (SIRENE) chargé en totalité, national et tous secteurs, car un titulaire de marché informatique peut être immatriculé sous n'importe quel code NAF.

## 2. Architecture générale

Le pipeline suit une architecture **bronze / silver / gold**, implémentée dans `db/schema.sql` et les scripts du dossier `scripts/`.

- **Bronze** (`bronze_decp_marches`, `bronze_ted_notices`) : copie brute des sources, append-only. Une ré-exécution après mise à jour côté source ajoute des lignes sans jamais écraser les précédentes — c'est le mécanisme de versionnement.
- **Silver** (`silver_marches`, `silver_attributions`) : reconstruite en totalité à chaque exécution de `transformer_silver_marches.py`, à partir de la version la plus récente de chaque marché en bronze. Schéma unifié DECP/TED, identifiants résolus via `resolution_identite.py` (niveaux 2 et 3, cf. section 4), doublons inter-sources détectés et flagués sans être supprimés.
- **Gold** (`acheteurs`, `marches`, `entreprises`, `attributions`, `etablissements`) : tables métier peuplées par `construire_gold_marches.py` depuis silver, puis enrichies contre le référentiel SIRENE national par `enrichir_entreprises_depuis_sirene.py` et `enrichir_etablissements_depuis_sirene.py`.

```mermaid
flowchart TB
    subgraph Sources["Sources publiques"]
        DECP_SRC["Parquet DECP (data.gouv.fr)"]
        TED_SRC["API TED v3 (Search Notices)"]
        SIRENE_SRC["API Sirene (INSEE)"]
        STOCK_SRC["Stock SIRENE national<br/>(fichiers .zip, data/sirene/)"]
    end

    subgraph Connecteurs
        C_DECP["connectors/decp.py"]
        C_TED["connectors/ted.py"]
        C_SIRENE["connectors/sirene.py"]
    end

    DECP_SRC --> C_DECP --> CBD["charger_bronze_decp.py"]
    TED_SRC --> C_TED --> CBT["charger_bronze_ted.py"]

    CBD --> BDM[("bronze_decp_marches")]
    CBT --> BTN[("bronze_ted_notices")]

    STOCK_SRC --> ISSN["importer_stock_sirene_national.py"]
    ISSN --> SSUL[("sirene_stock_unite_legale")]
    ISSN --> SSE[("sirene_stock_etablissement")]
    SSUL --> NSS["nettoyer_stock_sirene.py<br/>(index trigram pg_trgm)"]
    SSE --> NSS

    BDM --> TSM["transformer_silver_marches.py<br/>+ resolution_identite.py (niv. 2/3)"]
    BTN --> TSM
    NSS -. "SIREN seul -> SIRET siège<br/>rapprochement flou" .-> TSM

    TSM --> SM[("silver_marches")]
    TSM --> SA[("silver_attributions")]

    SM --> CGM["construire_gold_marches.py"]
    SA --> CGM

    CGM --> ACH[("acheteurs")]
    CGM --> MAR[("marches")]
    CGM --> ENT[("entreprises")]
    CGM --> ATT[("attributions")]

    NSS --> EED["enrichir_entreprises_depuis_sirene.py"]
    ENT --> EED --> ENT
    NSS --> EES["enrichir_etablissements_depuis_sirene.py"]
    ATT --> EES --> ETB[("etablissements")]
    SIRENE_SRC --> C_SIRENE --> CAS["completer_via_api_sirene.py"]
    ENT --> CAS --> ENT

    MAR --> GEM["generer_embeddings_marches.py"]
    GEM --> MAR
    MAR --> MSI["marches_similaires.py"]
    ATT --> GCO["graphe_concurrentiel.py"]

    MAR --> DS["detecter_sortant.py"]
    ATT --> DS
    ENT --> DS
    DS --> FDF["fiche_de_faits.py"]
    FDF --> VRB["verbaliser.py"]
    FDF --> BDD["bloc_de_decision.py"]
    VRB --> VME["verification_mecanique.py"]
```

**Tech stack vérifiable** (`requirements.txt`) : PostgreSQL (extensions `pg_trgm` et `vector`/pgvector), SQLAlchemy + psycopg2, DuckDB (filtrage du Parquet DECP côté client), `sentence-transformers` (embeddings locaux), pytest. Aucune dépendance à une API LLM externe.

## 3. Frontière déterministe / agentique, et sa justification

Tout ce qui est construit dans ce projet (S1 à S5, S7, la partie faite de S8) est du **code déterministe** : requêtes SQL, règles de normalisation par expression régulière, seuils numériques fixes, gabarit de texte strict (`verbaliser.py` ne contient aucune génération libre, uniquement des f-strings sur des valeurs déjà validées). Rejouer le pipeline sur les mêmes données produit exactement le même résultat.

Trois cas, explicitement listés dans `scripts/harnais_evaluation.py` (fonction `cas_non_implementes`) et repris dans le README comme S6, ne sont pas construits :

1. **Homonymie non résoluble par le nom seul** (niveau 4 de la résolution d'identité). Le rapprochement flou (niveau 3, `pg_trgm`) compare des chaînes de caractères ; quand plusieurs entreprises françaises partagent *exactement* la même dénomination (ex. « SMILE », mesuré à 112 cas réels dans le référentiel SIRENE via `tests/donnees/jeu_test_resolution_identite.csv`), aucun seuil de similarité ne peut les distinguer, car la chaîne comparée est identique pour toutes. Trancher demande un signal que le pipeline actuel n'a pas structurellement à disposition dans une seule requête déterministe (proximité géographique avec l'acheteur, secteur d'activité cohérent avec l'objet du marché, recoupement d'autres sources) — c'est un arbitrage sous incertitude avec plusieurs indices faibles, pas un calcul.
2. **Marché passé par une centrale d'achat.** Un marché notifié par une centrale d'achat est rattaché en base au SIRET de la centrale, pas à l'organisme réellement bénéficiaire. Une détection fiable suppose de reconnaître qu'un acheteur *est* une centrale d'achat (à partir d'un signal indirect, ex. catégorie juridique ou volume disproportionné de marchés très divers) puis d'ajuster la déclaration de couverture en conséquence — un jugement contextuel, pas une jointure.
3. **Changement de raison sociale.** Le sujet demande explicitement une « résolution correcte OU doute signalé » : distinguer un changement de nom légitime d'une simple homonymie demande de croiser plusieurs indices (continuité du SIREN, cohérence temporelle) et de formuler un degré de confiance argumenté — au-delà d'un seuil de similarité fixe.

Ce choix de périmètre est défendable comme une **frontière de nature**, pas seulement une limite de temps : les parties construites (S1-S5, S7, S8 partiel) sont toutes des transformations reproductibles d'une donnée déjà présente en base vers une autre donnée déterminée sans ambiguïté par des règles fixes. Les trois cas ci-dessus demandent au contraire de peser des indices contradictoires ou incomplets et d'assumer un jugement — exactement la distinction que `scripts/harnais_evaluation.py` matérialise en listant ces cas comme `NON IMPLÉMENTÉ` plutôt que de les simuler avec une règle fragile qui donnerait une fausse impression de couverture.

## 4. Résolution d'identité

Implémentée dans `scripts/resolution_identite.py`, appelée par `transformer_silver_marches.py` pour tout identifiant qui échoue au niveau 1 (SIRET exact 14 chiffres).

- **Niveau 2 — normalisation (déterministe)** : suppression des espaces internes, éclatement des champs multi-valeurs (plusieurs SIRET concaténés dans un même champ — co-traitance cachée), résolution d'un SIREN seul vers le SIRET du siège via `sirene_stock_etablissement`, extraction du SIREN depuis une TVA intracommunautaire française, détection d'une TVA étrangère (catégorisée `etranger`, jamais confondue avec un résultat français).
- **Niveau 3 — rapprochement flou (probabiliste)** : uniquement si le niveau 2 échoue et qu'un nom est disponible. `similarity()` (`pg_trgm`) contre `sirene_stock_unite_legale`, seuil 0.55, meilleur candidat retenu avec son score (`score_confiance`), jamais un résultat sans score.

**Méthodologie du jeu de test** : `tests/donnees/jeu_test_resolution_identite.csv`, 39 cas (confirmé par comptage de lignes du fichier), construits à partir de couples (nom, SIREN) réels vérifiés contre le référentiel SIRENE, complétés par des cas ciblant les pièges du sujet. Mesuré par `python scripts/mesurer_precision_resolution.py` — résultat obtenu en relançant cette commande le 10/08/2026 :

| Catégorie | Résultat |
|---|---|
| `niveau2_espaces` | 1/1 (100%) |
| `niveau2_prefixe` | 1/1 (100%) |
| `niveau2_multivaleurs` | 1/1 (100%) |
| `niveau2_siren_seul` | 1/1 (100%) |
| `niveau2_tva_fr` | 1/1 (100%) |
| `niveau2_etranger` | 2/2 (100%) |
| `niveau3_flou` | 18/18 (100%) |
| `niveau3_flou_parenthese` | 2/2 (100%) |
| `niveau3_flou_forme_juridique` | 2/2 (100%) |
| `niveau3_flou_forme_juridique_construit` | 2/2 (100%) |
| `niveau3_flou_ambigu` (homonymie réelle) | 2/6 (33%) |
| `impossible_par_nom` | 0/1 (0%) |
| `impossible` (entreprise inexistante) | 1/1 (100%) |
| **Niveau 2 (agrégé)** | **7/7 (100%)** |
| **Niveau 3 (agrégé, inclut `ambigu` et `impossible*`)** | **27/32 (84%)** |
| **Global** | **34/39 (87%)** |
| **Hors homonymie (`ambigu` exclus)** | **32/33 (97%)** |

**Analyse honnête des échecs** :
- `niveau3_flou_ambigu` (2/6, 33%) : cas d'homonymie réelle où plusieurs entreprises françaises partagent exactement la même dénomination (ex. « SMILE », 112 cas mesurés dans le référentiel). Le rapprochement par similarité de chaîne ne peut structurellement pas les départager — c'est précisément le cas réservé au niveau 4 (agent), cf. section 3.
- `impossible_par_nom` (0/1) : cas d'un entrepreneur individuel dont le champ `denominationUniteLegale` est vide dans le stock SIRENE (les personnes physiques y sont enregistrées sous des champs nom/prénom, pas dénomination) — un échec structurel de l'approche par nom, différent de l'homonymie, et non couvert par le seuil de similarité.

La cible du sujet (>90%, France) est atteinte hors homonymie (97%) mais pas sur le chiffre global (87%) — écart documenté tel quel, cause identifiée précisément ci-dessus, pas masqué derrière une moyenne unique.

## 5. Détection du sortant et chaînes de renouvellement

Implémentée dans `scripts/detecter_sortant.py`. Pour un couple (acheteur, CPV), la fonction `detecter_sortant()` :

1. Regroupe les marchés au niveau `uid` (un accord-cadre à plusieurs titulaires ne compte qu'une fois dans la chaîne temporelle, même si `historique` conserve le détail par titulaire).
2. Pour chaque marché, calcule une date de fin **estimée** : `date_notification` + durée. La durée utilisée est soit la durée **réellement publiée** par la source (`duree_mois`, champ DECP — jamais disponible pour TED, cf. limites section 7), soit, si absente, la **durée médiane observée sur ce même code CPV** tous acheteurs confondus (`_duree_mediane_cpv`). Chaque résultat porte son `duree_source` (`"reelle"` ou `"inferee_famille_cpv"`) et **aucune durée n'est inventée** si ni l'une ni l'autre n'est disponible (`date_fin_estimee = None`).
3. Regroupe les marchés notifiés à moins de 30 jours d'intervalle (`FENETRE_GENERATION_JOURS`) en une même « vague » de notification (plusieurs lots d'un accord-cadre attribués ensemble ne doivent pas être lus comme une séquence de renouvellement).
4. Évalue la cohérence de la chaîne : une transition entre deux vagues est jugée cohérente si l'écart entre fin estimée et vague suivante reste sous 6 mois (`SEUIL_COHERENCE_MOIS`). Le niveau de confiance (`aucune`/`faible`/`moyenne`/`élevée`) dépend du nombre de vagues **et** du taux de cohérence de la chaîne, pas seulement du volume de marchés — un acheteur avec de nombreux marchés temporellement incohérents sur un CPV générique n'obtient jamais `élevée`.

Ce mécanisme se propage dans `fiche_de_faits.py`, qui dégrade explicitement la couverture d'un fait quand la donnée sous-jacente est estimée plutôt que publiée (`couverture_expiration` réduite de moitié si la durée est inférée par médiane CPV, nulle si aucune durée n'est disponible) — jamais un chiffre calculé présenté avec la même certitude qu'une donnée source.

## 6. Métriques

**Avertissement méthodologique** : le sujet original (document externe à ce dépôt) n'étant pas directement accessible depuis ce contexte, le tableau ci-dessous reconstruit les métriques et pièges de la « section 8 » à partir de ce que le code du projet cite explicitement comme provenant de cette section (`grep -rn "section 8"` sur `scripts/`), et non recopié depuis le document source lui-même. Chaque ligne est vérifiée par une commande reproductible, relancée le 10/08/2026.

| Exigence (section 8, telle que référencée dans le code) | Cible | Mesure au 10/08/2026 | Commande |
|---|---|---|---|
| Précision résolution d'identité (France) | > 90% | **87%** global / **97%** hors homonymie | `python scripts/mesurer_precision_resolution.py` |
| Piège « Concurrent hors France » → dégradé + déclaré | déclenchement réel, pas simulé | **PASS** — déclaré=True, dégradé=True (couverture=0.33), compté=True | `python scripts/harnais_evaluation.py` |
| Piège « CPV mal saisi » → complété par similarité | déclenchement réel | **PASS** — cas découvert dynamiquement (CPV 72267100), 5 marchés à CPV différent retournés avec score, meilleur cas ≥ 0.6 trouvé | `python scripts/harnais_evaluation.py` |
| Piège « Changement de raison sociale » → résolution correcte OU doute signalé | — | **NON IMPLÉMENTÉ** (agent, S6, hors périmètre — cf. section 3) | `python scripts/harnais_evaluation.py` |
| Piège « Marché passé par une centrale d'achat » → limite de couverture signalée | — | **NON IMPLÉMENTÉ** (agent, S6, hors périmètre — cf. section 3) | `python scripts/harnais_evaluation.py` |
| Bloc de décision ≤ 10 lignes | ≤ 10 lignes | **PASS** — 8 lignes sur le cas testé | `python scripts/harnais_evaluation.py` |
| Anti-hallucination (aucun chiffre non sourcé dans le texte généré) | 0 chiffre non justifié | **PASS** | `python scripts/harnais_evaluation.py` (+ `pytest tests/test_verification_mecanique.py`) |
| Couverture jamais présentée comme 100% trompeur | — | **PASS** | `python scripts/harnais_evaluation.py` |
| Cohérence référentiel SIRENE (stock, enrichissement, orphelins) | 8 contrôles | **8/8** | `python scripts/verification_finale_sirene.py` |
| Suite de tests | — | **33/33 passed** (31 tests fonctionnels initiaux + 2 tests de régression ajoutés le 10/08 sur un cas de plantage corrigé, cf. `git log`) | `pytest tests/` |

## 7. Limites de données assumées

Synthèse de la section « Limites de données connues » du `README.md`, revérifiée à la date de ce rapport :

- **Homonymie non résoluble par le nom seul** : précision mesurée à 33% sur ce sous-type (cf. section 4), réservée au niveau 4 (agent), hors périmètre.
- **25 marchés (9 DECP + 16 TED) sans acheteur exploitable** même après les niveaux 2/3 de résolution.
- **Chevauchement DECP/TED** : 41 doublons probables inter-sources détectés et flagués (`doublon_probable_de`), jamais supprimés silencieusement ; la ligne DECP est retenue comme référence en gold.
- **TED : dates simplifiées** — `date_notification` et `date_publication` prennent la même valeur (l'API ne distingue pas ces deux dates au niveau du champ utilisé) ; `duree_mois`/`duree_restante_mois` restent `NULL` pour tous les marchés TED (aucune durée inférée pour ne pas fabriquer une donnée absente au niveau de la table `marches` — l'inférence par médiane CPV n'intervient qu'en aval, dans `detecter_sortant.py`, cf. section 5).
- **7 entreprises marquées `INTROUVABLE_API`** (404 sur l'API Sirene au moment du passage) : à traiter par un futur agent d'investigation d'identité hors SIRENE.
- **86 SIRET titulaires sans établissement correspondant** dans le stock national (établissement fermé/radié avant l'historique disponible, ou SIRET mal saisi côté source).
- **Rapprochement flou potentiellement lent** sur les noms courts/fréquents (`similarity()` contre ~29,8M lignes), sans cache entre appels identiques au sein d'une même exécution — acceptable au volume actuel, à revoir si le volume grossit significativement.
- **Bronze non purgé automatiquement** : chaque exécution des scripts de chargement ajoute des lignes sans purge des versions anciennes — acceptable à l'échelle du stage, une politique de rétention serait nécessaire en production.
- **Filiales non modélisées** dans `graphe_concurrentiel.py` : aucun dataset de liens de succession/structure de groupe n'est chargé dans ce projet ; une heuristique par adresse/préfixe SIREN produirait des rapprochements non fiables, documentée comme limite plutôt que simulée.

## 8. Pistes d'extension

Reprise et mise en contexte de la section « Prochaines étapes » du README (`README.md`, section du même nom) :

- **S6 — Agents** (niveau 4 identité, centrale d'achat, changement de raison sociale) : les trois cas justifiés en section 3. `scripts/harnais_evaluation.py` les garde visibles comme `NON IMPLÉMENTÉ` plutôt que masqués, pour que l'écart reste mesurable à chaque exécution du harnais.
- **Passerelle LLM** : aucune n'est configurée dans ce projet. Prérequis technique aux trois agents S6. Les embeddings (S4) utilisent volontairement un modèle local (`sentence-transformers`) pour ne pas en dépendre ; la verbalisation (S7) reste un gabarit texte strict, pas une génération par LLM.
- **Pondération acheteur (prix/technique)** : le fait `ponderation_acheteur` existe déjà dans `fiche_de_faits.py` (couverture toujours à 0.0, valeur `"non disponible"`), en attente d'une source de données supplémentaire (ex. règlement de consultation / CCTP du marché) qu'aucun connecteur actuel ne fournit.

## Annexe

### A. Instructions de reproduction

```bash
# Installation
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# copier .env.example vers .env, renseigner DATABASE_URL et SIRENE_API_KEY
# installer pgvector, puis : psql -U stage_user -d marches_publics -f db/schema.sql

# Les 4 commandes de vérification citées dans ce rapport
pytest tests/
python scripts/harnais_evaluation.py
python scripts/mesurer_precision_resolution.py
python scripts/verification_finale_sirene.py
```

Détail du pipeline de données complet (10 étapes, ordre d'exécution) : voir `README.md`, section « Pipeline de données ».

### B. Tableau récapitulatif des 8 semaines du sujet

Mapping S1-S8 reconstruit à partir des références explicites dans le code (commentaires citant `section 6, S1/S2/S4/S5` dans `connectors/ted.py`, `scripts/charger_bronze_decp.py`, `scripts/charger_bronze_ted.py`, `scripts/transformer_silver_marches.py`, `scripts/generer_embeddings_marches.py`, `scripts/graphe_concurrentiel.py`, `scripts/detecter_sortant.py`, `scripts/harnais_evaluation.py`) et de l'historique `git log`. S6, S7 et S8 ne sont pas nommés explicitement dans le code sous cette forme ; leur contenu est déduit de la structure du sujet telle que citée par ailleurs (agents, fiche de faits/verbalisation, bloc de décision) — signalé comme tel.

| Semaine | Contenu (déduit du code et du sujet cité) | État vérifié | Preuve |
|---|---|---|---|
| S1 | Environnement, schéma DB, connecteurs SIRENE/DECP/TED | ✅ | `connectors/*.py` fonctionnels, `pytest tests/test_sirene.py tests/test_decp.py tests/test_ted.py` passent |
| S2 | Ingestion bronze/silver/gold, déduplication, versionnement | ✅ | `pytest tests/test_bronze_silver_gold.py` passe (3 tests) |
| S3 | Résolution d'identité (hiérarchie SIRET → normalisation → flou), jeu de test annoté | ✅ | 87% global / 97% hors homonymie, cf. section 4 |
| S4 | Embeddings sémantiques, `marches_similaires.py`, `graphe_concurrentiel.py` | ✅ | `pytest tests/test_marches_similaires.py tests/test_graphe_concurrentiel.py` passent ; couverture embeddings 100% (cf. README) |
| S5 | Détection du sortant, chaînes de renouvellement | ✅ | `pytest tests/test_detecter_sortant.py` passe, cf. section 5 |
| S6 | Agents (niveau 4 identité, centrale d'achat, changement de raison sociale) | ⛔ | Non implémenté par choix assumé (section 3) ; listé explicitement dans `harnais_evaluation.py` |
| S7 | Fiche de faits, verbalisation par gabarit, vérification mécanique anti-hallucination | ✅ | `pytest tests/test_verification_mecanique.py` passe (5 tests) |
| S8 | Bloc de décision final (≤10 lignes), harnais d'évaluation | 🟡 | Bloc de décision et harnais fonctionnels (`pytest tests/test_bloc_de_decision.py`, 8/8 harnais) ; pondération acheteur non disponible, 2 cas agents non couverts — limites assumées et documentées, pas masquées |

---

## Points non vérifiés directement — à valider avant diffusion

Liste des affirmations que je n'ai **pas** pu confirmer par le code, les tests ou une commande, et qui sont donc formulées avec prudence ou signalées comme telles dans le corps du rapport plutôt qu'affirmées :

1. **Le texte exact du sujet** (sections 1 à 9) : je n'ai accès qu'aux citations qu'en fait le code en commentaire (`grep "section X"`), jamais au document source lui-même. Le tableau de métriques (section 6) et le mapping S1-S8 (annexe B) sont donc des **reconstructions**, pas des recopies fidèles — signalé explicitement à chaque endroit concerné.
2. **Contenu précis de S6, S7 et S8 tel que numéroté dans le sujet** : ces trois numéros de semaine n'apparaissent nulle part littéralement dans le code (contrairement à S1, S2, S4, S5, trouvés par `grep`). Leur contenu (agents pour S6, fiche de faits/verbalisation pour S7, bloc de décision pour S8) est déduit de la description fonctionnelle du sujet citée ailleurs dans le README et le code, pas confirmé par une référence directe « S6 »/« S7 »/« S8 » dans le dépôt.
3. ~~Ce qui s'est réellement passé lors des deux commits `dc153e3` et `61411d7`, tous deux intitulés à l'identique « Partie 4 : fiche de faits, verbalisation par gabarit, verification mecanique anti-hallucination »~~ — **vérifié après coup** (`git diff dc153e3 61411d7 --stat`) : ce ne sont pas des doublons, le second ajoute 7 lignes à `tests/test_verification_mecanique.py`. Point retiré de la liste des incertitudes, gardé ici pour traçabilité de la vérification.
4. **Le contexte organisationnel du stage** (entreprise d'accueil, encadrant, dates de début/fin du stage) : aucune information de ce type n'existe dans le dépôt ; ce rapport ne contient donc aucune page de garde ni section administrative — à compléter par vous si votre établissement l'exige.
