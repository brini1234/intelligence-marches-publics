# Intelligence concurrentielle sur les marchés publics

## Installation
1. `python3.11 -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. Copier `.env.example` vers `.env` et renseigner `DATABASE_URL` et `SIRENE_API_KEY`
4. Installer l'extension `pgvector` sur le serveur PostgreSQL utilisé (nécessaire à `db/schema.sql`, cf. section « Embeddings et graphe concurrentiel » plus bas pour la méthode retenue sur cette machine) — `brew install pgvector` suffit sur une installation Homebrew standard à jour ; sinon compiler contre le `pg_config` de la version réellement utilisée.
5. `psql -U stage_user -d marches_publics -f db/schema.sql` — `CREATE EXTENSION` (pg_trgm, vector) nécessite un compte PostgreSQL superutilisateur, pas nécessairement `stage_user` ; lancer ces deux lignes avec un compte superutilisateur si besoin avant le reste du script.

## Test rapide

```
pytest tests/
```

## Pipeline de données (périmètre CPV 72xxxxxx — services informatiques, France)

Le périmètre est celui proposé par le sujet, section 6 : *« services informatiques (CPV 72xxxxxx), France, historique de 3 à 5 ans »* — jamais un choix manuel d'acheteur, tout le périmètre est chargé automatiquement.

Architecture **bronze / silver / gold** (sujet, section 6, S2 : *« Ingestion TED et DECP sur CPV restreint, couches bronze/silver/gold, déduplication, versionnement »*), détaillée en commentaire dans `db/schema.sql` :

- **Bronze** (`bronze_decp_marches`, `bronze_ted_notices`) : copie brute, **append-only**, jamais écrasée. Relancer un chargement bronze après une mise à jour côté source ajoute des lignes plutôt que d'écraser les précédentes — c'est le **versionnement**.
- **Silver** (`silver_marches`, `silver_attributions`) : reconstruite entièrement à chaque exécution depuis la version la plus récente de chaque marché en bronze — c'est la **déduplication**. Schéma unifié DECP/TED, identifiants résolus selon la hiérarchie du sujet (section 5, détaillée ci-dessous). `silver_marches` porte les attributs de niveau marché ; `silver_attributions` porte les couples marché/titulaire séparément, **un accord-cadre pouvant avoir plusieurs titulaires** (jusqu'à 9 constatés sur le périmètre réel) — les fusionner en une seule ligne ferait disparaître des concurrents réels. Détecte aussi les doublons probables inter-sources (même acheteur, CPV, montant et date proches) et les flague (`doublon_probable_de`) sans jamais les supprimer.
- **Gold** (`marches`, `attributions`, `acheteurs`, `entreprises`, `etablissements`) : tables métier, structure inchangée, reconstruites depuis silver (les doublons flagués n'y créent pas de ligne séparée).

Étapes, dans l'ordre :

1. `python scripts/charger_bronze_decp.py` — export DECP filtré CPV 72xxxxxx via DuckDB (tous acheteurs du périmètre), chargement dans `bronze_decp_marches` par `COPY` + requête ensembliste (pas de boucle Python).
2. `python scripts/charger_bronze_ted.py` — avis d'attribution TED (`form-type=result`) du même périmètre, via `connectors/ted.py` (API Search TED v3, publique, sans clé), chargement dans `bronze_ted_notices`.
3. `python scripts/transformer_silver_marches.py` — bronze → silver : déduplication, validation, schéma unifié, résolution d'identité niveaux 2/3 (cf. section dédiée ci-dessous), détection des doublons inter-sources.
4. `python scripts/construire_gold_marches.py` — silver → gold : peuple `acheteurs`, `marches`, `entreprises`, `attributions`. Exclut les marchés sans SIRET acheteur valide et les doublons inter-sources flagués.
5. `python scripts/importer_stock_sirene_national.py` — charge les fichiers stock SIRENE (`data/sirene/*.zip`) en base via `COPY`. Le référentiel SIRENE reste **national et tous secteurs** (section 3 : *« SIRENE / France, toutes entreprises »*) même quand DECP/TED sont restreints à CPV72 : un titulaire de marché informatique peut être immatriculé sous n'importe quel code NAF.
6. `python scripts/nettoyer_stock_sirene.py` — normalise les valeurs vides, déduplique, verrouille les tables stock, crée l'index trigram (`pg_trgm`) nécessaire au rapprochement flou (résolution d'identité niveau 3).
7. `python scripts/enrichir_entreprises_depuis_sirene.py` puis `python scripts/enrichir_etablissements_depuis_sirene.py` — jointures SQL contre le référentiel national, indifféremment de la source (`DECP` ou `TED`) de chaque entreprise.
8. `python scripts/completer_via_api_sirene.py` — rattrapage via l'API SIRENE pour le résidu non couvert par le stock. Idempotent, ne retente jamais ce qui est déjà catégorisé définitivement.
9. `python scripts/verification_finale_sirene.py` — rapport de contrôle reproductible.
10. `python scripts/generer_embeddings_marches.py` — embeddings sémantiques des objets de marché (S4, cf. section dédiée ci-dessous), pour le rapprochement de marchés similaires malgré un CPV mal saisi.

Les fichiers stock SIRENE (`stock_unite_legale.zip`, `stock_etablissement.zip`, ~16 Go décompressés) doivent être placés dans `data/sirene/` avant l'étape 5 ; le Parquet DECP (`data/decp/decp.parquet`, ~235 Mo) est téléchargé automatiquement à la première exécution de l'étape 1. Les deux sont volontairement exclus du dépôt (`.gitignore`).

Pour élargir ponctuellement (ex. comparaison intersectorielle), `charger_bronze_decp(prefixe_cpv=None)` reste possible mais n'est pas le périmètre du stage.

## Résolution d'identité (sujet, section 5 : hiérarchie SIRET → normalisation → rapprochement flou → agent)

Niveau 1 (SIRET exact, 14 chiffres) résout la majorité des cas côté DECP directement. Mais l'exploration des données brutes a montré que **171 titulaires et 144 acheteurs TED** avaient un nom exploitable avec un identifiant dans un format non standard (espaces internes, SIRET multiples concaténés dans un même champ, SIREN seul, TVA intracommunautaire, TVA étrangère, identifiants internes TED sans structure). Les laisser exclus aurait fait disparaître jusqu'à 43.6% des marchés TED. `scripts/resolution_identite.py` implémente les niveaux 2 et 3, appelés automatiquement par `transformer_silver_marches.py` pour tout identifiant qui échoue au niveau 1 :

- **Niveau 2 (normalisation, déterministe — même certitude qu'un SIRET exact)** : suppression des espaces internes, éclatement des champs multi-valeurs (récupère plusieurs titulaires cachés dans une seule chaîne), résolution d'un SIREN seul vers le SIRET du siège via le référentiel SIRENE, extraction du SIREN depuis une TVA intracommunautaire française, détection d'une TVA étrangère (catégorisée `ETRANGER`, jamais confondue avec un résultat français — piège « concurrent hors France », section 8).
- **Niveau 3 (rapprochement flou, probabiliste)** : uniquement si le niveau 2 échoue et qu'un nom est disponible. `pg_trgm` (`similarity()`) contre `sirene_stock_unite_legale`, seuil 0.55, meilleur candidat retenu avec son score. Chaque résultat porte sa méthode (`methode_resolution`) et, pour le niveau 3, son score de confiance (`score_confiance`) — propagés jusqu'à `attributions` (gold) pour que les parties suivantes puissent signaler le doute plutôt que le masquer (section 8 : *« changement de raison sociale -> résolution correcte OU DOUTE SIGNALÉ »*).
- **Niveau 4 (agent)** : hors périmètre, comme les deux autres agents du sujet.

**Jeu de test annoté à la main** (`tests/donnees/jeu_test_resolution_identite.csv`, 39 cas) : construit à partir de couples (nom, SIREN) réels vérifiés directement contre le référentiel SIRENE (jamais de donnée inventée), complété par des cas construits pour les pièges du sujet (variante de raison sociale, filiale/marque commerciale, TVA étrangère, entrepreneur individuel, homonymie réelle, cas impossible). Mesuré par `python scripts/mesurer_precision_resolution.py` :

| | Précision |
|---|---|
| Niveau 2 (normalisation) | 7/7 (100%) |
| Niveau 3 (rapprochement flou) | 27/32 (84%) |
| **Global** | 34/39 (**87%**) |
| **Hors homonymie non résoluble par le nom seul** (cas réservés au niveau 4/agent par le sujet) | 32/33 (**97%**) |

La cible du sujet (section 8, >90%) n'est pas atteinte sur le chiffre global — documenté tel quel, pas masqué. La cause est précisément identifiée : le jeu de test inclut volontairement des cas d'homonymie réelle (ex. « SMILE » : 112 entreprises françaises partagent exactement cette dénomination, vérifié) que le sujet lui-même réserve au niveau 4 (agent), hors périmètre de cette étape. Hors ces cas, la précision est de 97%, au-dessus de la cible.

Effet mesuré sur la base réelle : **128 acheteurs et 164 couples marché/titulaire supplémentaires résolus**, portant les marchés sans acheteur exploitable de 153 à 25, et permettant pour la première fois au piège « concurrent hors France » (harnais d'évaluation) de se déclencher sur un cas réel plutôt que de rester en attente (`SKIP`).

## Embeddings et graphe concurrentiel (sujet, section 4 et 6 : S4)

Le sujet précise où les vecteurs interviennent, et nulle part ailleurs : *« rapprocher les objets de marché similaires, car les codes CPV sont mal saisis »*. Le reste (filiales, groupements, renouvellements) *« se modélise dans PostgreSQL avec des requêtes récursives »* — pas un moteur de graphe séparé.

- **`pgvector`** (extension requise, section 9) : non disponible via le paquet Homebrew standard sur cette machine (il ne compile que contre postgresql@17/18, alors que le serveur réel tourne en 16). Compilé manuellement contre postgresql@16 (`make PG_CONFIG=.../postgresql@16/bin/pg_config`, méthode officielle du projet pgvector) — nécessite un compte PostgreSQL superutilisateur pour `CREATE EXTENSION` (pas le compte applicatif `stage_user`).
- **Embeddings** (`scripts/generer_embeddings_marches.py`) : modèle local `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions, sentence-transformers) — aucune passerelle LLM externe n'étant configurée dans ce projet, un modèle local évite toute dépendance à une clé absente, pour une tâche qui n'a pas besoin de la qualité d'un grand modèle. **26 802/26 802 marchés couverts (100% de ceux ayant un objet non vide, sur 26 830 marchés au total)**, index HNSW (`idx_marches_objet_embedding`, distance cosinus) créé après peuplement. Script idempotent : ne recalcule que les `uid` sans embedding, donc sûr à relancer après chaque `construire_gold_marches.py`.
- **`scripts/marches_similaires.py`** : recherche par distance cosinus (`<=>`), retourne toujours un score de similarité — jamais un rapprochement présenté comme aussi certain qu'une correspondance exacte de CPV. Le piège « CPV mal saisi » du sujet (section 8) est **testé automatiquement dans `harnais_evaluation.py`**, sur un cas découvert dynamiquement à chaque exécution plutôt qu'un exemple figé en dur (les données évoluent) : au 10/08/2026, le marché le plus récent avec embedding (CPV 72267100, maintenance logicielle) retrouve 5 marchés à CPV différent, dont un à un score de 0.91 (CPV 72267000) — au-dessus du seuil de 0.6 retenu par le harnais.
- **`scripts/graphe_concurrentiel.py`** : requêtes `WITH RECURSIVE` sur les tables déjà en place, pas de nouvelle table de type graphe.
  - `co_titulaires_transitifs(siren, profondeur_max)` : groupements (co-traitance), directs et transitifs. Vérifié sur un accord-cadre réel (9 titulaires) : retrouve un réseau de co-traitance cohérent (ex. Wavestone, BearingPoint, CGI, Talan à profondeur 2).
  - `chaine_marches_acheteur(siret_acheteur, code_cpv)` : séquence chronologique des marchés d'un acheteur — la brique de traversée que S5 branchera sur `detecter_sortant.py` pour une vraie reconstitution de chaîne de renouvellement (pas fait ici : S4 livre la capacité, S5 l'utilisera).
- **Limite assumée : les *filiales* ne sont pas modélisées.** Aucun dataset de liens de succession/structure de groupe n'est chargé (le stock SIRENE utilisé ne le contient pas). Une heuristique (adresse ou préfixe SIREN partagés) produirait des rapprochements non fiables — contraire au principe déjà appliqué dans tout le projet (*« jamais fausser une jointure »*). Documenté comme limite, pas simulé.
- **Dépendances lourdes ajoutées** : `sentence-transformers` (entraîne `torch`, ~1,2 Go). Premier lancement : téléchargement du modèle (~470 Mo, une fois, mis en cache). Sur cette machine (CPU sans accélération), l'encodage initial de l'ensemble du périmètre a pris plusieurs dizaines de minutes — acceptable en tâche de fond ponctuelle, pas en chemin critique d'un briefing (le modèle reste chargé en mémoire pour les requêtes suivantes dans un même processus).

## Règle de sécurité des suppressions

À partir de maintenant, toute opération `DELETE` ou `UPDATE` affectant plus de 10 lignes sur une table métier (`entreprises`, `etablissements`, `acheteurs`, `marches`, `attributions`) doit respecter ce protocole :

1. créer une table de sauvegarde horodatée de type `backup_<nom>_<date>` avec une requête du type `CREATE TABLE backup_<nom>_<date> AS SELECT ... WHERE <condition>;`
2. afficher `SELECT COUNT(*)` sur la sélection ciblée pour valider le volume concerné ;
3. attendre confirmation explicite avant d’exécuter le `DELETE` ou l’`UPDATE`.

Exception assumée : les tables de stock brutes (`sirene_stock_unite_legale`, `sirene_stock_etablissement`) sont entièrement reconstruites à chaque exécution de `importer_stock_sirene_national.py` (`DROP` + `COPY` complet) — ce ne sont pas des données métier, donc leur nettoyage par `nettoyer_stock_sirene.py` n'a pas besoin de sauvegarde horodatée.

## Volumétrie et couverture (au 10/08/2026)

Périmètre : services informatiques (CPV 72xxxxxx), France, marchés notifiés/publiés sur une fenêtre de 3 ans, données actuelles uniquement. Deux sources d'attributions (DECP + TED, cf. pipeline ci-dessus). Le référentiel SIRENE reste chargé en totalité (national, tous secteurs).

| Table | Lignes | Rôle |
|---|---|---|
| bronze_decp_marches | 29 355 | brut DECP, append-only (26 560 uid distincts — l'écart, ~2 800 lignes, ce sont les modifications successives d'un même marché conservées par versionnement) |
| bronze_ted_notices | 666 | brut TED, append-only (336 publication_number distincts — même logique de versionnement qu'au-dessus, après un second chargement le 04/08) |
| silver_marches | 26 896 | un marché = une ligne, dédupliqué, validé, résolu (niveaux 1-3) |
| silver_attributions | 27 233 | un couple marché/titulaire = une ligne (plusieurs par marché possibles), résolu (niveaux 1-3) |
| acheteurs | 2 606 | gold |
| marches | 26 830 (26 551 DECP + 279 TED) | gold — silver_marches (26 896) moins 25 sans acheteur exploitable (niveaux 1-3 épuisés) et 41 doublons TED flagués |
| attributions | 27 170 | gold |
| entreprises | 5 748 | gold |
| etablissements | 6 922 | gold |
| sirene_stock_unite_legale | 29 803 585 | référentiel SIRENE |
| sirene_stock_etablissement | 43 700 154 | référentiel SIRENE |

**Couverture attribution : 24 745/26 830 marchés ont au moins un titulaire relié (92.2%).** Les marchés restants n'ont pas de titulaire relié en base car leur SIRET source est mal formé ou absent et non résolvable même via les niveaux 2/3 ; conformément au principe du sujet de ne jamais fausser une jointure, ces cas sont exclus plutôt qu'insérés avec un SIRET invalide.

**Déduplication inter-sources : 41 doublons probables DECP/TED détectés et flagués** (même acheteur, préfixe CPV, montant à moins de 1%, date à moins de 30 jours) — visibles dans `silver_marches.doublon_probable_de` pour audit, exclus de `marches` pour ne pas compter deux fois le même marché. En hausse par rapport à avant la résolution d'identité (22) : plus d'acheteurs/titulaires résolus, plus de correspondances DECP/TED détectables.

**Correction notable apportée par la séparation silver_marches / silver_attributions** : l'ancien pipeline (avant l'architecture bronze/silver/gold) pouvait perdre des titulaires sur les accords-cadres à attributaires multiples (`ON CONFLICT DO NOTHING` sur un seul SIRET titulaire par marché, ordre non déterministe). Un accord-cadre réel du périmètre a par exemple 9 titulaires distincts pour le même `uid` — tous désormais correctement conservés dans `silver_attributions`/`attributions`.

**Répartition des méthodes de résolution en gold (`attributions`)** : `siret_exact` 27 034, `flou` 80, `espaces` 31, `siren_seul` 15, `etranger` 6, `siret_exact_segmente` 3, `tva_fr` 1.

**Couverture SIRENE (`scripts/verification_finale_sirene.py`) : 8/8.** Stock national chargé en totalité, sans doublon de clé ; 100% des 5 748 entreprises ont un statut connu ; `etablissements` couvre 99% des SIRET titulaires réels (6 922/7 008) ; aucune dénomination vide, aucun établissement orphelin. **Le piège « concurrent hors France » (section 8 du sujet) se déclenche désormais réellement** : 5 entreprises marquées `ETRANGER` (détectées via la résolution d'identité niveau 2 sur des TVA intracommunautaires étrangères côté TED — invisibles avant, car ces identifiants ne matchaient jamais le niveau 1 et étaient simplement exclus). Le harnais d'évaluation confirme le déclenchement effectif (`déclaré=True, dégradé=True, compté=True`).

## Limites de données connues

- **Homonymie non résoluble par le nom seul** : la résolution niveau 3 (rapprochement flou) échoue structurellement quand plusieurs entreprises françaises partagent exactement la même dénomination (ex. « SMILE » : 112 cas réels, « BELHARRA » : 42) — le sujet réserve ce cas au niveau 4 (agent), hors périmètre actuel. Mesuré précisément à 33% de précision sur ce sous-type dans `tests/donnees/jeu_test_resolution_identite.csv`, documenté plutôt que masqué.
- **25 marchés (9 DECP + 16 TED) restent sans acheteur exploitable** même après les niveaux 2/3 : identifiant brut sans structure reconnue et sans rapprochement flou concluant sur le nom.
- **Chevauchement DECP/TED** : un même marché au-dessus des seuils européens peut légitimement apparaître à la fois dans DECP et dans TED. Détecté et flagué (`doublon_probable_de`) plutôt que silencieusement dupliqué — 41 cas identifiés sur ce périmètre. La ligne DECP est retenue comme référence (SIRET titulaire plus fiable, section 3 du sujet), la ligne TED reste visible en silver pour audit mais n'entre pas dans `marches`.
- **TED : dates simplifiées** — `date_notification` et `date_publication` prennent la même valeur (`publication-date` de l'avis TED), TED ne distinguant pas ces deux dates au niveau du champ testé, contrairement à DECP. `duree_mois`/`duree_restante_mois` restent `NULL` pour les marchés TED : l'API ne renvoie pas de durée simple exploitable à ce niveau d'agrégation, et aucune durée n'est inférée pour ne pas fabriquer une donnée absente.
- 7 entreprises marquées `INTROUVABLE_API` (404 sur l'API Sirene) : non résolvables via le référentiel SIRENE au moment du passage — à traiter par un futur agent d'investigation d'identité hors SIRENE plutôt que retentées en boucle.
- 86 SIRET titulaires (7 008 − 6 922) sans établissement correspondant dans le stock national : établissement fermé/radié avant l'historique disponible, ou SIRET mal saisi côté source.
- L'API Sirene applique une limite d'environ 30 requêtes/minute (au-delà : `429 Too Many Requests`) ; `completer_via_api_sirene.py` respecte ce débit et peut nécessiter plusieurs passages successifs sur un gros résidu.
- **Rapprochement flou lent sur les noms courts/fréquents** : une requête `similarity()` contre 29,8M lignes peut prendre de 1 à 20 secondes selon la rareté du nom, même avec l'index trigram (`idx_sirene_stock_unite_legale_denom_trgm`) et le seuil `pg_trgm.similarity_threshold` relevé au niveau du seuil d'acceptation. Pas de cache entre appels identiques au sein d'une même exécution — acceptable pour le volume actuel (quelques centaines de résolutions par run), à revoir si le volume grossit significativement.
- **Bronze non purgé automatiquement** : chaque exécution de `charger_bronze_decp.py`/`charger_bronze_ted.py` ajoute des lignes (c'est le versionnement voulu) sans jamais en supprimer — sur de nombreuses ré-exécutions successives sans changement source, `bronze_decp_marches` grossit sans purge automatique des versions anciennes. Acceptable à l'échelle du stage (8 semaines) ; une politique de rétention serait nécessaire en production.
- Sauvegardes horodatées disponibles en base : `backup_*_20260803` (recadrage national → CPV72), `backup_*_pre_bsg_20260803` (avant reconstruction bronze/silver/gold) et `backup_*_pre_s3_20260803` (avant résolution d'identité) — conservées par sécurité, non utilisées par le pipeline.

## Prochaines étapes (hors périmètre assumé de cette livraison)

Deux points du sujet ne sont volontairement pas construits à ce stade — limites assumées, pas oubliées :

- **S6 — Agents** : le sujet (section 4) prévoit trois agents — **investigation d'identité** (SIRET manquant ou rapprochement ambigu ; recouvre le niveau 4 de résolution d'identité pour l'homonymie non résoluble par le nom seul, cf. section ci-dessus, et le piège « changement de raison sociale »), **expansion pilotée par la couverture** (élargit la recherche — acheteurs comparables, périmètre géographique, CPV parent, fenêtre temporelle — quand la couverture est insuffisante, et sait conclure à des données insuffisantes ; couvre le piège « marché passé par une centrale d'achat »), et **enrichissement web** (recherche sur corpus ouvert en dégradation gracieuse — explicitement optionnel pour S6 selon le sujet, *« si le temps le permet »*). Aucun n'est implémenté. `scripts/harnais_evaluation.py` liste explicitement `NON IMPLÉMENTÉ` les deux pièges qui en dépendent (jamais masqués en `PASS`), pour qu'ils restent visibles comme travail restant plutôt que silencieusement omis.
- **Passerelle LLM** : aucune passerelle vers un grand modèle de langage n'est configurée dans ce projet. Les embeddings (S4) utilisent un modèle local pour cette raison (cf. section dédiée). La verbalisation (S7, `scripts/verbaliser.py`) reste un gabarit texte strict, pas une génération par LLM. Une passerelle serait le prérequis technique aux trois agents S6 ci-dessus.
- **Pondération acheteur (prix/technique)** : le fait `ponderation_acheteur` existe dans `scripts/fiche_de_faits.py` mais vaut toujours `"non disponible"` (couverture 0.0) — aucune source connectée (DECP, TED) ne publie les critères de pondération d'un marché. Non résolvable sans une source de données supplémentaire (ex. RC/CCTP du marché), hors périmètre des connecteurs actuels.