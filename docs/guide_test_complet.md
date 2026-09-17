# Guide de test complet — module par module

Contrairement à `docs/script_demonstration_10min.md` (déroulé minuté pour la soutenance) et `docs/guide_demonstration.md` (checklist + Q&A de la démo), ce document sert à **tester soi-même chaque partie du système, indépendamment**, avant une démonstration ou pour vérifier une modification. Chaque partie donne : ce qu'elle fait, sa commande de test automatisé, le résultat attendu, et une commande manuelle pour l'observer en direct.

Toutes les commandes ci-dessous ont été exécutées et vérifiées le 17/09/2026 sur l'état réel du dépôt et de la base.

**Prérequis, à faire une fois avant tout le reste :**

```bash
cd "C:\Users\USER\Desktop\intelligence-marches-publics\intelligence-marches-publics"
venv\Scripts\python.exe -c "import psycopg2; psycopg2.connect('postgresql://stage_user:...@localhost:5432/marches_publics', connect_timeout=5); print('OK')"
```

Si la connexion échoue (PostgreSQL portable, pas un service Windows) :

```bash
"C:\Users\USER\pgsql16\extracted\pgsql\bin\pg_ctl.exe" start -D "C:\Users\USER\pgsql16\data" -l "C:\Users\USER\pgsql16\data\logfile.txt"
```

---

## Partie 0 — Tout d'un coup (si le temps manque)

```bash
venv\Scripts\python.exe -m pytest tests/ -q
```
Attendu : `84 passed, 4 skipped`.

```bash
venv\Scripts\python.exe scripts/harnais_evaluation.py
```
Attendu : `10/10 vérifications automatisées réussies`.

Si ces deux commandes passent, chaque partie ci-dessous passera aussi — elles ne font que zoomer sur un sous-ensemble de la même suite.

---

## Partie 1 — Connecteurs (sources brutes)

Ce que ça fait : parle directement aux API/fichiers sources (DECP, TED, SIRENE, BOAMP), avant toute écriture en base.

```bash
venv\Scripts\python.exe -m pytest tests/test_decp.py tests/test_ted.py tests/test_sirene.py tests/test_boamp.py -v
```
Attendu : tous verts. Ce sont des tests unitaires sur la logique de parsing/filtrage des connecteurs (`connectors/*.py`), pas des appels réseau réels à chaque run.

Observer un connecteur en direct (réseau réel, optionnel) :
```bash
venv\Scripts\python.exe -c "
from connectors.sirene import rechercher_par_siret
print(rechercher_par_siret('11000028800016'))
"
```

---

## Partie 2 — Pipeline bronze / silver / gold (l'import, sans étape manuelle)

Ce que ça fait : bronze = copie brute intégrale (France, 3 ans, **tous secteurs**, jamais un acheteur ou un CPV choisi à la main) ; silver = nettoyage/dédup/résolution d'identité niveaux 1-3 ; gold = filtre métier CPV 72xxxxxx appliqué **seulement à cette étape**, jamais avant.

**Preuve que rien n'est manuel** : aucun script d'ingestion ne prend de paramètre d'acheteur ou de SIRET particulier —
```bash
grep -n "def charger_bronze_ted\|def construire_gold_marches" scripts/charger_bronze_ted.py scripts/construire_gold_marches.py
```
donne des fonctions sans argument (`charger_bronze_ted()`, `construire_gold_marches()`) : le périmètre est un paramètre de code versionné (`PREFIXE_CPV_PERIMETRE`), jamais une saisie humaine à l'exécution.

```bash
venv\Scripts\python.exe -m pytest tests/test_bronze_silver_gold.py -v
```
Attendu : tous verts (déduplication, filtre CPV appliqué en gold seulement, accord-cadre multi-titulaires préservé).

Vérifier la volumétrie réelle en base :
```bash
venv\Scripts\python.exe -c "
from db.connection import get_engine
from sqlalchemy import text
engine = get_engine()
with engine.connect() as c:
    for t in ['bronze_decp_marches','bronze_ted_notices','silver_marches','silver_attributions','marches','attributions']:
        print(t, c.execute(text(f'SELECT count(*) FROM {t}')).scalar())
"
```
Attendu (17/09/2026) : `bronze_decp_marches` 1 178 240, `bronze_ted_notices` 102 081, `silver_marches` 1 042 553, `silver_attributions` 1 102 951, `marches` 27 299, `attributions` 29 030.

Relancer tout le pipeline depuis zéro (plusieurs heures, seulement si les sources source ont changé) :
```bash
venv\Scripts\python.exe scripts/charger_bronze_decp.py
venv\Scripts\python.exe scripts/charger_bronze_ted.py
venv\Scripts\python.exe scripts/transformer_silver_marches.py
venv\Scripts\python.exe scripts/construire_gold_marches.py
venv\Scripts\python.exe scripts/importer_stock_sirene_national.py
venv\Scripts\python.exe scripts/nettoyer_stock_sirene.py
venv\Scripts\python.exe scripts/enrichir_entreprises_depuis_sirene.py
venv\Scripts\python.exe scripts/enrichir_etablissements_depuis_sirene.py
venv\Scripts\python.exe scripts/completer_via_api_sirene.py
venv\Scripts\python.exe scripts/generer_embeddings_marches.py
```

---

## Partie 3 — Résolution d'identité (SIRET → nom → entreprise réelle)

Ce que ça fait : hiérarchie SIRET exact → normalisation → rapprochement flou → agent, exactement comme demandé par le sujet (section 5).

```bash
venv\Scripts\python.exe -m pytest tests/test_resolution_identite.py -v
```

```bash
venv\Scripts\python.exe scripts/mesurer_precision_resolution.py
```
Attendu : **92% global, 100% hors homonymie** (cible sujet : >90%, atteinte) — mesuré sur `tests/donnees/jeu_test_resolution_identite.csv` (39 cas annotés à la main).

```bash
venv\Scripts\python.exe scripts/verification_finale_sirene.py
```
Attendu : `8/8` (cohérence du référentiel SIRENE : pas de doublon, pas d'orphelin, 100% des entreprises catégorisées).

---

## Partie 4 — Embeddings et graphe concurrentiel (S4)

Ce que ça fait : rapproche des objets de marché similaires malgré un CPV mal saisi (embeddings) ; traverse les groupements/chaînes d'acheteur en SQL récursif (pas de moteur de graphe séparé).

```bash
venv\Scripts\python.exe -m pytest tests/test_marches_similaires.py tests/test_graphe_concurrentiel.py -v
```

```bash
venv\Scripts\python.exe scripts/graphe_concurrentiel.py
```
Montre la co-traitance transitive sur un accord-cadre réel.

```bash
venv\Scripts\python.exe -c "
from scripts.marches_similaires import trouver_marches_similaires
from db.connection import get_engine
from sqlalchemy import text
engine = get_engine()
with engine.connect() as c:
    m = c.execute(text(\"SELECT uid, objet, code_cpv FROM marches WHERE objet_embedding IS NOT NULL ORDER BY date_notification DESC LIMIT 1\")).fetchone()
print('Référence :', m.code_cpv, '-', m.objet[:70])
for r in trouver_marches_similaires(uid=m.uid, limite=5, exclure_meme_cpv=True):
    print(f\"  score={r['similarite']:.2f}  cpv={r.get('code_cpv')}  {r.get('objet','')[:60]}\")
"
```
Attendu : au moins un marché à CPV différent avec un score ≥ 0.6 (piège « CPV mal saisi » du sujet).

---

## Partie 5 — Détection du sortant

Ce que ça fait : le vrai morceau algorithmique du sujet — reconstitue les chaînes de renouvellement, estime une échéance, produit un sortant probable avec un niveau de confiance.

```bash
venv\Scripts\python.exe -m pytest tests/test_detecter_sortant.py -v
```

```bash
venv\Scripts\python.exe scripts/mesurer_precision_sortant.py
```
Attendu : **6/6 (100%)** sur le SIREN du sortant, sur `tests/donnees/jeu_test_detecter_sortant.csv` (7 cas réels, 1 exclu et documenté car structurellement indécidable).

---

## Partie 6 — Les 3 agents (S6)

### 6a. Investigation d'identité (le plus rentable des trois selon le sujet)

```bash
venv\Scripts\python.exe -m pytest tests/test_agent_investigation_identite.py -v
```

```bash
venv\Scripts\python.exe -c "
from db.connection import get_engine
from scripts.agent_investigation_identite import investiguer_via_historique_sirene
engine = get_engine()
with engine.connect() as c:
    print(investiguer_via_historique_sirene('FRANCE TELECOM', c))
"
```
Attendu : SIREN 380129866 retrouvé (changement de raison sociale France Télécom → Orange, 2013) — piège « changement de raison sociale ».

### 6b. Expansion pilotée par la couverture

```bash
venv\Scripts\python.exe -m pytest tests/test_agent_expansion_couverture.py -v
```

```bash
venv\Scripts\python.exe -c "
from scripts.bloc_de_decision import construire_bloc_de_decision, afficher_bloc
lignes = construire_bloc_de_decision('77605646700587', '72220000', 'UGAP')
afficher_bloc(lignes)
"
```
Attendu : `DONNÉES INSUFFISANTES : Marché notifié par une centrale d'achat` — piège « marché passé par une centrale d'achat ».

### 6c. Enrichissement web (dégradation gracieuse)

```bash
venv\Scripts\python.exe -m pytest tests/test_agent_enrichissement_web.py -v
```
2 des 5 tests peuvent apparaître `skipped` si DuckDuckGo répond par un défi anti-bot (aléa réseau externe, jamais un échec de logique) — comportement attendu, documenté dans le README.

---

## Partie 7 — Fiche de faits, verbalisation, porte anti-hallucination, bloc de décision

```bash
venv\Scripts\python.exe -m pytest tests/test_fiche_de_faits.py tests/test_verification_mecanique.py tests/test_bloc_de_decision.py tests/test_schemas.py -v
```

Voir la fiche de faits JSON brute (ce que reçoit un LLM, et rien d'autre) :
```bash
venv\Scripts\python.exe -c "
import json
from scripts.fiche_de_faits import construire_fiche_de_faits
print(json.dumps(construire_fiche_de_faits('11000028800016', '72220000'), indent=2, ensure_ascii=False, default=str))
"
```
Vérifier que chaque entrée porte bien `provenance` et `couverture` — c'est le mécanisme anti-hallucination (section 4 du sujet).

Voir le bloc de décision final (l'entrée simple → sortie du sujet, section 1) :
```bash
venv\Scripts\python.exe scripts/bloc_de_decision.py
```
Attendu : 8 lignes (≤ 10 imposées), sortant + concurrents + fourchette de prix + pondération + couverture globale.

Vérification mécanique anti-hallucination en isolation (un chiffre inventé est rejeté) :
```bash
venv\Scripts\python.exe -m pytest tests/test_verification_mecanique.py::test_texte_avec_chiffre_invente_est_rejete -v
```

Verbalisation par LLM (optionnelle, nécessite `ANTHROPIC_API_KEY` dans `.env`) :
```bash
venv\Scripts\python.exe -m pytest tests/test_verbaliser_llm.py -v
```
Sans clé : ces 2 tests apparaissent `skipped`, comportement attendu (le chemin par défaut du produit, `scripts/verbaliser.py`, ne dépend d'aucune clé).

---

## Partie 8 — Harnais d'évaluation global (les 5 pièges du sujet, section 8)

```bash
venv\Scripts\python.exe scripts/harnais_evaluation.py
```
Attendu : `10/10` — couvre les 5 pièges de soutenance (acheteur sans historique, centrale d'achat, CPV mal saisi, changement de raison sociale, concurrent hors France) + 5 contrôles structurels (anti-hallucination, 5 éléments du bloc, couverture honnête, limite de 10 lignes).

---

## Partie 9 — Les 6 métriques du sujet (section 8)

| Métrique | Commande | Attendu |
|---|---|---|
| Précision résolution d'identité | `python scripts/mesurer_precision_resolution.py` | 92% (>90% requis) |
| Précision détection du sortant | `python scripts/mesurer_precision_sortant.py` | 6/6 (100%) |
| Coût et latence par briefing | `python scripts/mesurer_cout_latence_briefing.py` | 0,00 € ; latence 60-600 ms selon le cas |
| Couverture par section | `python scripts/mesurer_couverture_sections.py` | affichée par fait, jamais masquée |
| Taux d'affirmations sourcées / taux d'hallucination | garantie architecturale (voir `docs/rapport_de_stage.md`, section 6, note) | non mesurables par échantillon — rendus structurellement impossibles à violer |

---

## Partie 10 — Le test « appel d'offre » : de l'acheteur/objet réels au bloc de décision sourcé

C'est le test qui rejoue exactement le scénario du sujet (section 1) : *« entrée simple (un acheteur, un objet de marché), sortie sous forme de fiche JSON et de rapport lisible »*.

```bash
venv\Scripts\python.exe -c "
from scripts.bloc_de_decision import construire_bloc_de_decision, afficher_bloc
# Remplacer par le SIRET acheteur, le code CPV et le nom réels de l'appel d'offres visé
lignes = construire_bloc_de_decision('<SIRET_ACHETEUR>', '<CODE_CPV>', '<NOM_ACHETEUR>')
afficher_bloc(lignes)
"
```

Trois issues possibles, toutes correctes par construction :
1. **Cas riche** : bloc de 5 à 8 lignes, sortant probable + concurrents + fourchette de prix + couverture (ex. Cour des Comptes, `11000028800016` / `72220000`).
2. **Cas pauvre** : l'agent d'expansion (couverture insuffisante) élargit automatiquement (CPV parent, acheteurs comparables) avant de répondre — plus lent (jusqu'à ~500 ms) mais jamais un GO/No-Go inventé.
3. **Cas impossible** : `DONNÉES INSUFFISANTES`, explicite — acheteur sans historique, ou marché passé par une centrale d'achat.

Dans les trois cas, la commande suivante montre la preuve derrière chaque ligne du bloc :
```bash
venv\Scripts\python.exe -c "
import json
from scripts.fiche_de_faits import construire_fiche_de_faits
print(json.dumps(construire_fiche_de_faits('<SIRET_ACHETEUR>', '<CODE_CPV>'), indent=2, ensure_ascii=False, default=str))
"
```

---

## Résumé — une commande par partie

```bash
pytest tests/test_decp.py tests/test_ted.py tests/test_sirene.py tests/test_boamp.py -q          # Partie 1
pytest tests/test_bronze_silver_gold.py -q                                                        # Partie 2
pytest tests/test_resolution_identite.py -q && python scripts/mesurer_precision_resolution.py     # Partie 3
pytest tests/test_marches_similaires.py tests/test_graphe_concurrentiel.py -q                     # Partie 4
pytest tests/test_detecter_sortant.py -q && python scripts/mesurer_precision_sortant.py           # Partie 5
pytest tests/test_agent_expansion_couverture.py tests/test_agent_investigation_identite.py tests/test_agent_enrichissement_web.py -q  # Partie 6
pytest tests/test_fiche_de_faits.py tests/test_verification_mecanique.py tests/test_bloc_de_decision.py tests/test_schemas.py -q      # Partie 7
python scripts/harnais_evaluation.py                                                              # Partie 8
python scripts/mesurer_cout_latence_briefing.py && python scripts/mesurer_couverture_sections.py  # Partie 9
python scripts/bloc_de_decision.py                                                                # Partie 10
```

Ou, en une seule commande pour tout valider d'un coup :
```bash
pytest tests/ -q && python scripts/harnais_evaluation.py && python scripts/verification_finale_sirene.py
```
