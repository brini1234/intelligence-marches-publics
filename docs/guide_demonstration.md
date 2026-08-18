# Guide de démonstration — validation jalon mi-parcours (fin S5)

Ce guide sert à préparer et rejouer la présentation en direct. Toutes les commandes ci-dessous ont été exécutées et vérifiées le 16/08/2026 ; les sorties citées sont réelles, pas des exemples reconstruits.

## Avant la présentation (à faire la veille ou le matin même)

```bash
cd /Users/chaimabrini/intelligence-marches-publics
source venv/bin/activate

# 1. PostgreSQL doit tourner. En cas de doute :
brew services list | grep postgres
pg_isready
```

**Si `pg_isready` répond "no response"** (déjà arrivé deux fois sur cette machine — fichier de verrou périmé) :

```bash
brew services stop postgresql@16
rm -f /usr/local/var/postgresql@16/postmaster.pid
brew services start postgresql@16
sleep 3
pg_isready   # doit répondre "accepting connections"
```

Cette opération ne touche à aucune donnée (juste un fichier de verrou système).

```bash
# 2. Suite de tests complète (~1-2 min)
pytest tests/ -q
# attendu : 38 passed

# 3. Harnais d'évaluation (pièges de démonstration du sujet)
python scripts/harnais_evaluation.py
# attendu : 10/10 automatisés réussis, 0 cas restant (tous les pièges du sujet couverts)

# 4. Contrôle SIRENE
python scripts/verification_finale_sirene.py
# attendu : 8/8
```

Si les quatre commandes passent, la base et le code sont dans l'état présenté dans les slides — pas besoin de rejouer tout le pipeline d'ingestion (plusieurs heures) avant une démo.

## Pendant la présentation — les commandes à montrer en direct

### A. L'exemple central : une fiche de faits complète, de bout en bout (jalon S5)

```bash
python -c "
import sys; sys.path.append('.')
from scripts.bloc_de_decision import construire_bloc_de_decision, afficher_bloc
lignes = construire_bloc_de_decision('11000028800016', '72220000', 'COUR DES COMPTES')
afficher_bloc(lignes)
"
```

Sortie attendue (8 lignes, ≤ 10 imposées par le sujet) :

```
============================================================
1. Acheteur : COUR DES COMPTES | Objet CPV : 72220000
2. Sortant probable : ALTERMES (couverture: 100%)
3. Échéance estimée : 2026-12-21 (dernier marché: 2026-07-21) (couverture: 100%)
4. Concurrents observés : RSM FRANCE (1/11 attribution(s)), GRANT THORNTON (3/11 attribution(s)), CTF CONSEIL (3/11 attribution(s)), ERNST ET YOUNG ADVISORY (...) (2/11 attribution(s)), PRICEWATERHOUSECOOPERS ADVISORY (1/11 attribution(s)) (couverture: 100%)
5. Fourchette de prix : 41,864 € — 95,840 € (n=11, indicatif)
6. Pondération de l'acheteur : non disponible (couverture: 0%)
7. Historique : 11 marché(s) similaire(s) observé(s)
8. COUVERTURE GLOBALE : 89%
============================================================
```

Points à commenter en le montrant :
- ligne 5 : jamais "prix du marché : X €", toujours une fourchette + n + "indicatif" (vocabulaire imposé, sujet section 2) ;
- ligne 6 : "non disponible" plutôt que masqué — aucune source connectée ne publie la pondération ;
- couverture affichée à chaque ligne, jamais un 100% de façade sur l'ensemble (89% global, tiré vers le bas par la pondération à 0%).

### B. La fiche de faits JSON sous-jacente (chaque chiffre tracé à sa source)

```bash
python -c "
import sys, json; sys.path.append('.')
from scripts.fiche_de_faits import construire_fiche_de_faits
print(json.dumps(construire_fiche_de_faits('11000028800016', '72220000'), indent=2, ensure_ascii=False, default=str))
"
```

À montrer : chaque fait porte `provenance` et `couverture` — c'est cet objet, et uniquement lui, que recevrait un modèle de langage pour verbaliser (S7).

### C. Résolution d'identité — précision mesurée

```bash
python scripts/mesurer_precision_resolution.py
```

Attendu : 87% global / 97% hors homonymie (cible sujet : >90%, atteinte hors le cas explicitement réservé à l'agent S6/niveau 4).

### D. Embeddings — CPV mal saisi retrouvé par similarité (S4)

```bash
python -c "
import sys; sys.path.append('.')
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

Résultat vérifié le 16/08 : marché de référence en CPV 72267100 ("Maintenance Logiciel Isilog"), meilleur rapprochement à score 0.91 sur un CPV différent (72267000) — au-dessus du seuil de 0.6 retenu.

### E. Graphe concurrentiel — co-traitance transitive (S4)

```bash
python scripts/graphe_concurrentiel.py
```

Exemple réel obtenu le 16/08 (SIREN 378615363) : 19 co-traitants retrouvés à profondeur 1-2, dont Wavestone, BearingPoint, CGI, Talan, MC2I, Orange Business Services — via `WITH RECURSIVE` sur les tables existantes, aucune table de graphe séparée.

### F. Agent d'investigation d'identité — changement de raison sociale (S6, niveau 4)

```bash
python -c "
import sys; sys.path.append('.')
from db.connection import get_engine
from scripts.agent_investigation_identite import investiguer_via_historique_sirene
engine = get_engine()
with engine.connect() as c:
    print(investiguer_via_historique_sirene('FRANCE TELECOM', c))
"
```

Résultat vérifié : `{'siret': '38012986600...', 'siren': '380129866', 'methode': 'investigation_historique_denomination', 'score_confiance': 0.8}` — France Télécom a changé de raison sociale pour Orange en 2013 (même SIREN, vérifié en direct sur l'API SIRENE). Point à commenter : un homonyme *actuel* sans rapport existe aussi (SIREN 441965027) — le mécanisme ne le confond jamais avec un renommage car seules les périodes *passées* comptent.

### G. Filet de sécurité si le réseau/la base a un problème pendant la démo

- Les captures d'écran/sorties ci-dessus sont déjà dans ce document et dans les slides — en cas de souci technique en direct, les montrer telles quelles plutôt que d'improviser.
- `pytest tests/ -q` et `python scripts/harnais_evaluation.py` sont les deux commandes de repli les plus rapides (~1-2 min) pour prouver que l'état du dépôt est sain sans dérouler d'exemple métier.

## Questions probables et où trouver la réponse

| Question | Réponse courte | Détail |
|---|---|---|
| Pourquoi 87% et pas 90% sur la résolution d'identité ? | Le seul sous-type en échec (homonymie réelle, ex. "SMILE" : 112 entreprises françaises identiques) est traité par le niveau 4 (agent d'investigation d'identité, implémenté) : 2/6 cas résolus légitimement via l'historique SIRENE, 4/6 restent structurellement indécidables (aucun contexte acheteur, aucun historique de renommage). Hors homonymie : 97%. | `docs/rapport_de_stage.md`, section 4 et 11 |
| Le sortant est-il fiable ? | Confiance calculée (aucune/faible/moyenne/élevée) selon le nombre de vagues de marchés ET leur cohérence temporelle, jamais juste le volume. | `scripts/detecter_sortant.py` |
| Que se passe-t-il si l'acheteur n'a aucun historique ? | `DONNÉES INSUFFISANTES`, jamais un sortant inventé — testé dans le harnais. | `python scripts/harnais_evaluation.py` |
| Et les filiales ? | Non modélisées volontairement (aucun dataset de structure de groupe chargé) ; documenté comme limite assumée plutôt que simulé par heuristique non fiable. | `scripts/graphe_concurrentiel.py`, docstring |
| Qu'est-ce qui reste à faire ? | S6 (agent d'enrichissement web, seul agent restant, explicitement optionnel selon le sujet), S8 (mesures coût/latence, précision du sortant sur cas connus). S7 (verbalisation, porte de vérification, bloc de décision) est fait. | `docs/rapport_de_stage.md`, section 8 |
