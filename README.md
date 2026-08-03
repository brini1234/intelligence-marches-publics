# Intelligence concurrentielle sur les marchés publics

## Installation
1. `python3.11 -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. Copier `.env.example` vers `.env` et renseigner `DATABASE_URL` et `SIRENE_API_KEY`
4. `psql -U stage_user -d marches_publics -f db/schema.sql`

## Test rapide

```
pytest tests/
```

## Pipeline de données (périmètre CPV 72xxxxxx — services informatiques, France)

Le périmètre est celui proposé par le sujet, section 6 : *« services informatiques (CPV 72xxxxxx), France, historique de 3 à 5 ans »* — jamais un choix manuel d'acheteur, tout le périmètre est chargé automatiquement.

Architecture **bronze / silver / gold** (sujet, section 6, S2 : *« Ingestion TED et DECP sur CPV restreint, couches bronze/silver/gold, déduplication, versionnement »*), détaillée en commentaire dans `db/schema.sql` :

- **Bronze** (`bronze_decp_marches`, `bronze_ted_notices`) : copie brute, **append-only**, jamais écrasée. Relancer un chargement bronze après une mise à jour côté source ajoute des lignes plutôt que d'écraser les précédentes — c'est le **versionnement**.
- **Silver** (`silver_marches`, `silver_attributions`) : reconstruite entièrement à chaque exécution depuis la version la plus récente de chaque marché en bronze — c'est la **déduplication**. Schéma unifié DECP/TED, SIRET validés (14 chiffres exacts, sinon `NULL` — jamais inventé). `silver_marches` porte les attributs de niveau marché ; `silver_attributions` porte les couples marché/titulaire séparément, **un accord-cadre pouvant avoir plusieurs titulaires** (jusqu'à 9 constatés sur le périmètre réel) — les fusionner en une seule ligne ferait disparaître des concurrents réels. Détecte aussi les doublons probables inter-sources (même acheteur, CPV, montant et date proches) et les flague (`doublon_probable_de`) sans jamais les supprimer.
- **Gold** (`marches`, `attributions`, `acheteurs`, `entreprises`, `etablissements`) : tables métier, structure inchangée, reconstruites depuis silver (les doublons flagués n'y créent pas de ligne séparée).

Étapes, dans l'ordre :

1. `python scripts/charger_bronze_decp.py` — export DECP filtré CPV 72xxxxxx via DuckDB (tous acheteurs du périmètre), chargement dans `bronze_decp_marches` par `COPY` + requête ensembliste (pas de boucle Python).
2. `python scripts/charger_bronze_ted.py` — avis d'attribution TED (`form-type=result`) du même périmètre, via `connectors/ted.py` (API Search TED v3, publique, sans clé), chargement dans `bronze_ted_notices`.
3. `python scripts/transformer_silver_marches.py` — bronze → silver : déduplication, validation, schéma unifié, détection des doublons inter-sources.
4. `python scripts/construire_gold_marches.py` — silver → gold : peuple `acheteurs`, `marches`, `entreprises`, `attributions`. Exclut les marchés sans SIRET acheteur valide et les doublons inter-sources flagués.
5. `python scripts/importer_stock_sirene_national.py` — charge les fichiers stock SIRENE (`data/sirene/*.zip`) en base via `COPY`. Le référentiel SIRENE reste **national et tous secteurs** (section 3 : *« SIRENE / France, toutes entreprises »*) même quand DECP/TED sont restreints à CPV72 : un titulaire de marché informatique peut être immatriculé sous n'importe quel code NAF.
6. `python scripts/nettoyer_stock_sirene.py` — normalise les valeurs vides, déduplique, verrouille les tables stock.
7. `python scripts/enrichir_entreprises_depuis_sirene.py` puis `python scripts/enrichir_etablissements_depuis_sirene.py` — jointures SQL contre le référentiel national, indifféremment de la source (`DECP` ou `TED`) de chaque entreprise.
8. `python scripts/completer_via_api_sirene.py` — rattrapage via l'API SIRENE pour le résidu non couvert par le stock. Idempotent, ne retente jamais ce qui est déjà catégorisé définitivement.
9. `python scripts/verification_finale_sirene.py` — rapport de contrôle reproductible.

Les fichiers stock SIRENE (`stock_unite_legale.zip`, `stock_etablissement.zip`, ~16 Go décompressés) doivent être placés dans `data/sirene/` avant l'étape 5 ; le Parquet DECP (`data/decp/decp.parquet`, ~235 Mo) est téléchargé automatiquement à la première exécution de l'étape 1. Les deux sont volontairement exclus du dépôt (`.gitignore`).

Pour élargir ponctuellement (ex. comparaison intersectorielle), `charger_bronze_decp(prefixe_cpv=None)` reste possible mais n'est pas le périmètre du stage.

## Règle de sécurité des suppressions

À partir de maintenant, toute opération `DELETE` ou `UPDATE` affectant plus de 10 lignes sur une table métier (`entreprises`, `etablissements`, `acheteurs`, `marches`, `attributions`) doit respecter ce protocole :

1. créer une table de sauvegarde horodatée de type `backup_<nom>_<date>` avec une requête du type `CREATE TABLE backup_<nom>_<date> AS SELECT ... WHERE <condition>;`
2. afficher `SELECT COUNT(*)` sur la sélection ciblée pour valider le volume concerné ;
3. attendre confirmation explicite avant d’exécuter le `DELETE` ou l’`UPDATE`.

Exception assumée : les tables de stock brutes (`sirene_stock_unite_legale`, `sirene_stock_etablissement`) sont entièrement reconstruites à chaque exécution de `importer_stock_sirene_national.py` (`DROP` + `COPY` complet) — ce ne sont pas des données métier, donc leur nettoyage par `nettoyer_stock_sirene.py` n'a pas besoin de sauvegarde horodatée.

## Volumétrie et couverture (au 03/08/2026)

Périmètre : services informatiques (CPV 72xxxxxx), France, marchés notifiés/publiés sur une fenêtre de 3 ans, données actuelles uniquement. Deux sources d'attributions (DECP + TED, cf. pipeline ci-dessus). Le référentiel SIRENE reste chargé en totalité (national, tous secteurs).

| Table | Lignes | Rôle |
|---|---|---|
| bronze_decp_marches | 29 355 | brut DECP, append-only (26 560 uid distincts — l'écart, ~2 800 lignes, ce sont les modifications successives d'un même marché conservées par versionnement) |
| bronze_ted_notices | 330 | brut TED, append-only |
| silver_marches | 26 890 | un marché = une ligne, dédupliqué, validé |
| silver_attributions | 27 063 | un couple marché/titulaire = une ligne (plusieurs par marché possibles) |
| acheteurs | 2 560 | gold |
| marches | 26 715 (26 551 DECP + 164 TED) | gold — silver_marches (26 890) moins 153 sans acheteur valide (9 DECP + 144 TED) et 22 doublons TED flagués |
| attributions | 27 021 | gold |
| entreprises | 5 702 | gold |
| etablissements | 6 871 | gold |
| sirene_stock_unite_legale | 29 803 585 | référentiel SIRENE |
| sirene_stock_etablissement | 43 700 154 | référentiel SIRENE |

**Couverture attribution : 24 598/26 715 marchés ont au moins un titulaire relié (92.1%).** Les marchés restants n'ont pas de titulaire relié en base car leur SIRET source est mal formé ou absent ; conformément au principe du sujet de ne jamais fausser une jointure, ces cas sont exclus plutôt qu'insérés avec un SIRET invalide.

**Déduplication inter-sources : 22 doublons probables DECP/TED détectés et flagués** (même acheteur, préfixe CPV, montant à moins de 1%, date à moins de 30 jours) — visibles dans `silver_marches.doublon_probable_de` pour audit, exclus de `marches` pour ne pas compter deux fois le même marché.

**Correction notable apportée par la séparation silver_marches / silver_attributions** : l'ancien pipeline (avant l'architecture bronze/silver/gold) pouvait perdre des titulaires sur les accords-cadres à attributaires multiples (`ON CONFLICT DO NOTHING` sur un seul SIRET titulaire par marché, ordre non déterministe). Un accord-cadre réel du périmètre a par exemple 9 titulaires distincts pour le même `uid` — tous désormais correctement conservés dans `silver_attributions`/`attributions`.

**Couverture SIRENE (`scripts/verification_finale_sirene.py`) : 7/8.** Stock national chargé en totalité, sans doublon de clé ; 100% des 5 702 entreprises ont un statut connu ; `etablissements` couvre 99% des SIRET titulaires réels (6 871/6 951) ; aucune dénomination vide, aucun établissement orphelin. Le seul contrôle en échec — *« titulaires hors France détectés et isolés »* — l'est légitimement : sur ce périmètre restreint, aucun identifiant hors France n'apparaît dans l'échantillon ; le piège « concurrent hors France » (section 8 du sujet) reste couvert par le code (`connectors/sirene.py`, `completer_via_api_sirene.py`), simplement non déclenché par ce jeu de données précis. Documenté tel quel plutôt que masqué.

## Limites de données connues

- **Couverture acheteur TED nettement plus faible que DECP** : sur 330 avis d'attribution TED récupérés (CPV72, France, 3 ans), 153 marchés au total (DECP + TED confondus) n'ont pas d'identifiant acheteur exploitable en silver et sont exclus de gold — jamais insérés avec un SIRET inventé.
- **Chevauchement DECP/TED** : un même marché au-dessus des seuils européens peut légitimement apparaître à la fois dans DECP et dans TED. Depuis l'architecture bronze/silver/gold, ce cas est désormais **détecté et flagué** (`doublon_probable_de`) plutôt que silencieusement dupliqué — 22 cas identifiés sur ce périmètre. La ligne DECP est retenue comme référence (SIRET titulaire plus fiable, section 3 du sujet), la ligne TED reste visible en silver pour audit mais n'entre pas dans `marches`.
- **TED : dates simplifiées** — `date_notification` et `date_publication` prennent la même valeur (`publication-date` de l'avis TED), TED ne distinguant pas ces deux dates au niveau du champ testé, contrairement à DECP. `duree_mois`/`duree_restante_mois` restent `NULL` pour les marchés TED : l'API ne renvoie pas de durée simple exploitable à ce niveau d'agrégation, et aucune durée n'est inférée pour ne pas fabriquer une donnée absente.
- 6 entreprises marquées `INTROUVABLE_API` (404 sur l'API Sirene) : non résolvables via le référentiel SIRENE au moment du passage — à traiter par un futur agent d'investigation d'identité hors SIRENE plutôt que retentées en boucle.
- 80 SIRET titulaires (6 951 − 6 871) sans établissement correspondant dans le stock national : établissement fermé/radié avant l'historique disponible, ou SIRET mal saisi côté source.
- L'API Sirene applique une limite d'environ 30 requêtes/minute (au-delà : `429 Too Many Requests`) ; `completer_via_api_sirene.py` respecte ce débit et peut nécessiter plusieurs passages successifs sur un gros résidu.
- **Bronze non purgé automatiquement** : chaque exécution de `charger_bronze_decp.py`/`charger_bronze_ted.py` ajoute des lignes (c'est le versionnement voulu) sans jamais en supprimer — sur de nombreuses ré-exécutions successives sans changement source, `bronze_decp_marches` grossit sans purge automatique des versions anciennes. Acceptable à l'échelle du stage (8 semaines) ; une politique de rétention serait nécessaire en production.
- Sauvegardes horodatées disponibles en base : `backup_*_20260803` (recadrage national → CPV72) et `backup_*_pre_bsg_20260803` (avant reconstruction bronze/silver/gold) — conservées par sécurité, non utilisées par le pipeline.