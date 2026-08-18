"""
Mesure le coût et la latence par briefing (sujet, section 8 : "Coût et
latence par briefing | mesurés").

Coût : 0,00 EUR par construction, pas une estimation — vérifié par lecture
directe (et `grep` transitif) des imports du chemin RÉELLEMENT emprunté par
construire_bloc_de_decision() : scripts/fiche_de_faits.py,
scripts/detecter_sortant.py, scripts/bloc_de_decision.py,
scripts/agent_expansion_couverture.py. Aucun de ces fichiers n'importe
`requests`, `httpx`, `urllib` ni `connectors.sirene` ; `agent_expansion_couverture.py`
interroge le référentiel SIRENE déjà chargé en base (tables
sirene_stock_*) via SQL, jamais l'API SIRENE elle-même. L'API SIRENE
n'intervient que dans des scripts de pipeline hors ligne
(completer_via_api_sirene.py, agent_investigation_identite.py en mode
__main__), jamais dans ce chemin. Aucune passerelle LLM n'est configurée
dans ce projet (README, rapport de stage) — verbaliser.py/
verification_mecanique.py existent mais ne sont PAS appelés par
construire_bloc_de_decision() (chemin séparé, emprunté par
harnais_evaluation.py), donc hors du périmètre chronométré ici.

Latence : chronométrée avec time.perf_counter() sur le chemin réellement
emprunté par un utilisateur (construire_bloc_de_decision, qui appelle
fiche_de_faits en interne), sur plusieurs cas représentatifs et plusieurs
répétitions — jamais une seule mesure présentée comme représentative. Un
appel de préchauffage (non chronométré) précède chaque série : le tout
premier appel du script entier subit un coût de démarrage (connexion
PostgreSQL, plan de requête froid) mesuré à part — vérifié en direct sur
cette machine, ce premier appel peut être ~4x plus lent que le régime
stable qui suit, un biais qui fausserait le "max" rapporté sans ce
préchauffage.

Usage :
    python scripts/mesurer_cout_latence_briefing.py
"""
import statistics
import sys
import time

sys.path.append(".")

from scripts.bloc_de_decision import construire_bloc_de_decision

NB_REPETITIONS = 5

# Quatre cas représentatifs, choisis pour exercer des chemins de code
# réellement distincts (pas seulement des noms différents) :
#   - riche : cas de référence cité partout dans la documentation.
#   - pauvre (déclenche l'agent d'expansion) : nb_marches_famille=1 < 2
#     (SEUIL_COUVERTURE_SUFFISANTE, scripts/agent_expansion_couverture.py)
#     -> exécute réellement les axes CPV parent + acheteurs comparables
#     NAF/département, le chemin le plus coûteux du dépôt. Vérifié :
#     "elargissement_applique" est bien présent dans la fiche de faits pour
#     ce cas.
#   - ambigu (ne déclenche PAS l'agent d'expansion) : nb_marches_famille=6
#     >= 2, la confiance est faible à cause d'un accord-cadre multi-
#     titulaires alternés, pas d'un manque de données — un cas différent
#     du précédent malgré une confiance également faible (correctif du
#     19/08/2026 : ce cas était auparavant étiqueté à tort "pauvre/ambigu"
#     alors qu'il ne passe jamais par l'agent d'expansion, trouvé par
#     revue de code indépendante).
#   - données insuffisantes : acheteur sans historique.
CAS_TEST = [
    ("11000028800016", "72220000", "COUR DES COMPTES", "riche"),
    ("05750620600036", "72500000", "SOCIETE D'HABITATIONS DES ALPES SA HLM (PLURALIS)",
     "pauvre, déclenche l'agent d'expansion"),
    ("22660001300016", "72250000", "DEPARTEMENT DES PYRENEES-ORIENTALES",
     "ambigu, n'élargit pas la recherche"),
    ("00000000000000", "99999999", "ACHETEUR INCONNU", "données insuffisantes"),
]


def mesurer_cout_latence():
    print("=" * 72)
    print("COÛT ET LATENCE PAR BRIEFING")
    print("=" * 72)
    print("Coût par briefing : 0,00 EUR — par construction, pas une estimation. Aucune "
          "passerelle LLM n'est configurée dans ce projet et aucun appel réseau ne se "
          "produit dans le chemin de génération d'un briefing (vérifié par lecture des "
          "imports, cf. docstring de ce script).")
    print("-" * 72)

    for siret, cpv, nom, type_cas in CAS_TEST:
        construire_bloc_de_decision(siret, cpv, nom)  # préchauffage, non chronométré

        durees = []
        for _ in range(NB_REPETITIONS):
            debut = time.perf_counter()
            construire_bloc_de_decision(siret, cpv, nom)
            durees.append(time.perf_counter() - debut)

        print(f"{nom} ({type_cas}) — {NB_REPETITIONS} répétitions, préchauffage exclu :")
        print(f"   min={min(durees) * 1000:.0f} ms   "
              f"médiane={statistics.median(durees) * 1000:.0f} ms   "
              f"max={max(durees) * 1000:.0f} ms")

    print("=" * 72)


if __name__ == "__main__":
    mesurer_cout_latence()
