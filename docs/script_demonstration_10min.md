# Script de démonstration — 10 minutes (sujet, section 7)

Déroulé minuté pour la soutenance. Toutes les commandes et sorties ci-dessous ont été ré-exécutées et vérifiées le 31/08/2026, puis revérifiées le 02/09/2026 (`docs/rapport_de_stage.md`, section 17) — pas des exemples reconstruits. Complément du guide plus large (`docs/guide_demonstration.md`, checklist avant-présentation, Q&A, filet de sécurité) : ce document-ci est le script à suivre minute par minute, lui reste la référence technique complète.

**Objectif du sujet (section 7)** : *« démonstration de 10 minutes : acheteur et objet de marché vers un bloc de décision source »*. Deux moments de démo live, un fil conducteur : partir d'un acheteur et d'un objet de marché, arriver à un bloc de décision, montrer qu'il est sourcé et honnête sur ce qu'il ne sait pas.

**Avant de commencer** : dérouler la checklist de `docs/guide_demonstration.md` (PostgreSQL up, `pytest tests/ -q` → 81 passed, 4 skipped, `harnais_evaluation.py` → 10/10). Terminal déjà ouvert dans le dépôt, `venv` déjà activé.

---

## 0:00 – 0:45 — Le problème (45s)

**À dire** : *« Avant d'investir 5 à 15 jours-homme dans une réponse à un appel d'offres, un commercial doit décider GO ou No-Go. Pour ça il a besoin de savoir : qui détient le marché aujourd'hui, contre qui il joue, à quel prix, et comment l'acheteur pondère ses critères. Aujourd'hui cette info se cherche à la main dans des archives publiques. Ce projet l'automatise — avec une contrainte forte : les marchés publics sont un domaine où la concurrence est publiée par la loi, donc rien n'est jamais inventé, tout sort d'une jointure sur des identifiants d'entreprise officiels. »*

Pas de terminal ici — uniquement le message.

## 0:45 – 1:30 — Ce que le système livre (45s)

**À dire** : *« Le système produit un bloc de décision de 10 lignes maximum, lisible en 30 secondes. Le vocabulaire est volontairement prudent : jamais "le sortant est X", toujours "sortant probable, avec sa couverture" ; jamais "prix du marché", toujours une fourchette avec la taille d'échantillon. »*

(Optionnel si le temps le permet : montrer le tableau formulation à éviter / formulation correcte du sujet, section 2 — sinon, l'expliquer oralement, la démo live du bloc juste après le montre concrètement.)

## 1:30 – 2:30 — Architecture en 3 principes (60s)

**À dire** : *« Trois principes : les faits sont calculés, jamais générés — tous les chiffres viennent de requêtes SQL, un modèle de langage se contente de les mettre en mots. Le bloc de décision que je vais montrer ne passe par aucun LLM — coût zéro, latence de quelques millisecondes ; une verbalisation par LLM existe par ailleurs pour un futur rapport détaillé en prose, avec sa propre porte de vérification anti-hallucination. Cœur déterministe, périphérie agentique — les trois agents prévus par le sujet sont implémentés, uniquement là où l'espace de recherche est réellement ouvert. Et la couverture est un citoyen de première classe — chaque section du briefing affiche son taux de complétude, jamais un 100% de façade. »*

Optionnel : montrer rapidement le schéma bronze/silver/gold du README si un support visuel est disponible.

## 2:30 – 5:30 — Démo live n°1 : le cas central (3 min)

**À dire en lançant** : *« Un acheteur réel, un objet de marché réel : la Cour des Comptes, conseil en systèmes informatiques. »*

```bash
python -c "
import sys; sys.path.append('.')
from scripts.bloc_de_decision import construire_bloc_de_decision, afficher_bloc
lignes = construire_bloc_de_decision('11000028800016', '72220000', 'COUR DES COMPTES')
afficher_bloc(lignes)
"
```

Sortie attendue (vérifiée le 31/08/2026, inchangée depuis le 21/08) :

```
============================================================
1. Acheteur : COUR DES COMPTES | Objet CPV : 72220000
2. Sortant probable : GRANT THORNTON (couverture: 100%)
3. Échéance estimée : 2027-01-21 (dernier marché: 2026-07-21) (couverture: 100%)
4. Concurrents observés : RSM FRANCE (1/11 attribution(s)), ALTERMES (1/11 attribution(s)), CTF CONSEIL (3/11 attribution(s)), PRICEWATERHOUSECOOPERS ADVISORY (1/11 attribution(s)), ERNST ET YOUNG ADVISORY (EY CONSULTING-EY PARTHENON-EY FABERNOVEL) (2/11 attribution(s)) (couverture: 100%)
5. Fourchette de prix : 41,864 € — 95,840 € (n=11, indicatif) (couverture: 100%)
6. Pondération de l'acheteur : non disponible (couverture: 0%)
7. Historique : 11 marché(s) similaire(s) observé(s)
8. COUVERTURE GLOBALE : 89%
============================================================
```

**Points à commenter (30s)** :
- ligne 5 : jamais un prix ponctuel, toujours une fourchette + n + « indicatif » ;
- ligne 6 : « non disponible » plutôt que masqué — aucune source connectée ne publie la pondération ;
- ligne 8 : 89%, pas 100% — tiré vers le bas par la pondération absente, jamais caché.

**À dire en enchaînant** : *« Ce bloc n'est pas rédigé par une IA à partir de rien — voici l'objet JSON exact qui l'alimente. »*

```bash
python -c "
import sys, json; sys.path.append('.')
from scripts.fiche_de_faits import construire_fiche_de_faits
print(json.dumps(construire_fiche_de_faits('11000028800016', '72220000'), indent=2, ensure_ascii=False, default=str))
"
```

**À montrer (30s)** : chaque entrée porte `provenance` et `couverture`. C'est cet objet, et uniquement lui, qui serait envoyé à un modèle de langage pour la verbalisation (S7) — jamais un accès libre à la base.

## 5:30 – 7:00 — Démo live n°2 : un piège (1 min 30)

**À dire** : *« Le sujet impose 5 pièges de comportement pour la soutenance. En voici un en direct : un marché passé par une centrale d'achat. »*

```bash
python -c "
import sys; sys.path.append('.')
from scripts.bloc_de_decision import construire_bloc_de_decision, afficher_bloc
lignes = construire_bloc_de_decision('77605646700587', '72000000', 'UGAP')
afficher_bloc(lignes)
"
```

Sortie attendue :

```
============================================================
1. Acheteur : UGAP | Objet CPV : 72000000
2. DONNÉES INSUFFISANTES : Marché notifié par une centrale d'achat (UNION DES GROUPEMENTS D'ACHATS PUBLICS (UGAP), détectée via le nom 'UGAP'). L'organisme bénéficiaire réel n'est pas identifiable dans les données disponibles : DECP/TED rattachent le marché au SIRET de la centrale, jamais à l'établissement final.
3. COUVERTURE GLOBALE : 0%
============================================================
```

**À dire** : *« L'UGAP a des milliers de marchés sous son propre SIRET — un système naïf afficherait un faux "sortant" avec confiance. Ici, la limite est détectée et déclarée avant tout calcul, jamais masquée. »*

**Si le temps le permet (sinon, mentionner oralement)** — un deuxième piège, changement de raison sociale :

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

Sortie : `{'siret': '38012986648625', 'siren': '380129866', 'methode': 'investigation_historique_denomination', 'score_confiance': 0.8}` — France Télécom a changé de raison sociale pour Orange en 2013, même SIREN, résolu via l'historique de l'API SIRENE.

## 7:00 – 8:30 — Les chiffres mesurés (1 min 30)

**À dire, sans montrer de terminal (gain de temps)** — citer de mémoire ou depuis une slide, vérifiés le 31/08/2026 et revérifiés le 02/09/2026 (`docs/rapport_de_stage.md`, section 17) :

- Suite de tests : **81 passed, 4 skipped** (2 `skipped` dépendent d'une vraie réponse de DuckDuckGo, niveau 5/agent web — aléa réseau, pas un échec ; 2 `skipped` nécessitent une clé Anthropic absente par défaut)
- Harnais d'évaluation (5 pièges du sujet) : **10/10**
- Précision de résolution d'identité : **92% global / 100% hors homonymie** — **cible sujet (>90%) atteinte**
- Précision de détection du sortant : **6/6 (100%)** sur cas connus
- Coût par briefing : **0,00 €** (le bloc de décision n'invoque aucun LLM) — latence **30-155 ms** selon le cas
- Contrôle référentiel SIRENE : **8/8**

*(Si le temps le permet, une seule commande pour appuyer : `python scripts/harnais_evaluation.py` → 10/10 en ~5 secondes.)*

## 8:30 – 9:30 — Limites assumées, pas cachées (1 min)

**À dire** : *« Une limite documentée, pas découverte en soutenance : une source sur six n'est pas connectée — Pappers/Infogreffe, API payante sans clé configurée. BOAMP l'est depuis fin août (recoupement/détection), et les sorties structurées prescrites par le sujet — Pydantic, JSON Schema — sont désormais validées systématiquement. Un résidu d'homonymie non résoluble par le nom seul subsiste aussi — ex. 112 entreprises françaises nommées "SMILE" — mais n'empêche plus d'atteindre la cible du sujet sur le chiffre global. »*

## 9:30 – 10:00 — Conclusion (30s)

**À dire** : *« Sur les 8 semaines du sujet : la base de données (import complet, filtrage CPV en aval), la résolution d'identité (92%, cible du sujet atteinte), la détection du sortant, les 3 agents prévus, la porte anti-hallucination, les sorties validées par Pydantic/JSON Schema, une verbalisation par LLM disponible, et les 6 métriques de la section 8 sont livrés et mesurés. Ce qui reste est documenté, pas caché — uniquement Pappers/Infogreffe, API payante sans clé configurée. »*

---

## Si le temps déborde (priorités de coupe)

Dans l'ordre où couper si le temps presse :
1. Le deuxième piège (changement de raison sociale) — mentionner le chiffre oralement plutôt que taper la commande.
2. La fiche de faits JSON — dire une phrase dessus sans l'afficher en entier.
3. Ne jamais couper : le bloc de décision central (2:30–5:30) et les chiffres mesurés (7:00–8:30) — c'est le cœur de la preuve.

## Filet de sécurité

Voir `docs/guide_demonstration.md`, section F : si le réseau ou la base a un problème en direct, les sorties de ce script sont déjà réelles et vérifiées — les montrer telles quelles (copier-coller à l'écran) plutôt que d'improviser une commande non répétée.
