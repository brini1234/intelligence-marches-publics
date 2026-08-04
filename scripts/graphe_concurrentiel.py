"""
Requêtes récursives sur le graphe concurrentiel (sujet, section 4 : "le
domaine est relationnel (filiales, groupements, renouvellements) et se
modélise dans PostgreSQL avec des requêtes récursives" ; section 6, S4).

Pas de nouvelle table de type graphe : les relations existent déjà dans le
schéma relationnel (marches, attributions, entreprises) — `WITH RECURSIVE`
suffit à les traverser. Deux traversées couvertes ici :

- Groupements (co-traitance) : une entreprise ayant partagé un marché avec
  une autre (accord-cadre multi-attributaires, cf. Partie 1) est un
  groupement direct ; transitivement, les co-traitants de ses co-traitants
  aussi, jusqu'à une profondeur bornée.
- Chaîne de marchés d'un acheteur (traversée temporelle, base de la future
  détection du sortant, S5) : succession des marchés d'un même acheteur sur
  un même CPV (ou objet sémantiquement proche via
  scripts/marches_similaires.py), triée par date.

Limite assumée : les *filiales* (relations société-mère/filiale) ne sont
PAS modélisées ici — aucun dataset de liens de succession/structure de
groupe n'est chargé dans ce projet (le stock SIRENE utilisé ne le contient
pas). Une heuristique (adresse ou préfixe SIREN partagés) produirait des
rapprochements non fiables, contraire au principe déjà appliqué dans tout
le projet ("jamais fausser une jointure") — documenté comme limite plutôt
que simulé.

Usage :
    python scripts/graphe_concurrentiel.py
"""
import sys

sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine


def co_titulaires_transitifs(siren: str, profondeur_max: int = 2) -> list[dict]:
    """
    Entreprises ayant partagé au moins un marché avec `siren`, directement
    (profondeur 1) ou transitivement via des co-titulaires communs jusqu'à
    `profondeur_max` sauts. Chaque résultat porte la profondeur à laquelle
    il a été atteint (jamais présenté comme un lien direct s'il ne l'est
    pas) et un marché support à titre d'exemple.
    """
    engine = get_engine()
    with engine.connect() as connexion:
        resultats = connexion.execute(text("""
            WITH RECURSIVE groupement AS (
                SELECT a2.siren_titulaire AS siren, 1 AS profondeur,
                       a1.uid_marche AS marche_support
                FROM attributions a1
                JOIN attributions a2 ON a2.uid_marche = a1.uid_marche
                                     AND a2.siren_titulaire != a1.siren_titulaire
                WHERE a1.siren_titulaire = :siren

                UNION

                SELECT a2.siren_titulaire, g.profondeur + 1, a1.uid_marche
                FROM groupement g
                JOIN attributions a1 ON a1.siren_titulaire = g.siren
                JOIN attributions a2 ON a2.uid_marche = a1.uid_marche
                                     AND a2.siren_titulaire != a1.siren_titulaire
                WHERE g.profondeur < :profondeur_max
                  AND a2.siren_titulaire != :siren
            )
            SELECT DISTINCT ON (g.siren) g.siren, e.denomination, g.profondeur, g.marche_support
            FROM groupement g
            JOIN entreprises e ON e.siren = g.siren
            ORDER BY g.siren, g.profondeur
        """), {"siren": siren, "profondeur_max": profondeur_max}).mappings().all()
    return [dict(r) for r in resultats]


def chaine_marches_acheteur(siret_acheteur: str, code_cpv: str) -> list[dict]:
    """
    Séquence chronologique des marchés d'un acheteur sur un CPV donné —
    la brique de traversée temporelle que la détection du sortant (S5,
    non refaite ici, cf. scripts/detecter_sortant.py) pourra utiliser pour
    reconstituer de vraies chaînes de renouvellement plutôt que de ne
    regarder que le marché le plus récent.
    """
    engine = get_engine()
    with engine.connect() as connexion:
        resultats = connexion.execute(text("""
            SELECT uid, objet, montant, date_notification, duree_mois,
                   ROW_NUMBER() OVER (ORDER BY date_notification) AS position_chaine
            FROM marches
            WHERE siret_acheteur = :siret_acheteur AND code_cpv = :code_cpv
            ORDER BY date_notification
        """), {"siret_acheteur": siret_acheteur, "code_cpv": code_cpv}).mappings().all()
    return [dict(r) for r in resultats]


if __name__ == "__main__":
    engine = get_engine()
    with engine.connect() as connexion:
        # Exemple réel : le SIREN d'un titulaire d'un accord-cadre multi-attributaires
        exemple = connexion.execute(text("""
            SELECT siren_titulaire FROM attributions
            GROUP BY uid_marche, siren_titulaire
            HAVING (SELECT COUNT(*) FROM attributions a2 WHERE a2.uid_marche = attributions.uid_marche) > 3
            LIMIT 1
        """)).fetchone()

    if exemple:
        print(f"Groupement transitif autour de {exemple.siren_titulaire} :")
        for r in co_titulaires_transitifs(exemple.siren_titulaire):
            print(f"  profondeur {r['profondeur']} | {r['denomination']} ({r['siren']}) "
                  f"| via {r['marche_support']}")
    else:
        print("Aucun accord-cadre multi-attributaires trouvé pour l'exemple.")
