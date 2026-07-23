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

## Volumétrie et couverture (au 23/07/2026)

Périmètre : 3 acheteurs publics (France Télévisions, Ville de Paris, Cour des Comptes), CPV informatique et travaux mixtes selon la phase de test.

| Table | Lignes |
|---|---|
| entreprises | 114 |
| acheteurs | 3 |
| marches | 150 |
| attributions | 148 |

**Couverture attribution : 148/150 marchés (98.7%).**

2 marchés (1.3%) n'ont pas de titulaire relié en base, car leur SIRET source est mal formé (exemples observés : `0438800071500` — 13 caractères au lieu de 14, `00001` — identifiant non conforme). Conformément au principe du sujet de ne jamais fausser une jointure, ces cas sont exclus plutôt qu'insérés avec un SIRET invalide.

La table `etablissements` n'est pas encore alimentée (limitation connue, sans impact sur les fonctionnalités actuelles de résolution d'identité et de détection du sortant).