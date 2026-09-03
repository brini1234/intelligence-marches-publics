"""
Mesure la précision de la hiérarchie de résolution d'identité (sujet,
section 5 et 8 : cible >90% pour la France) contre le jeu de test annoté
à la main (tests/donnees/jeu_test_resolution_identite.csv).

Chaque ligne teste soit un identifiant brut (niveau 2 : normalisation),
soit un nom seul (niveau 3 : rapprochement flou), avec un SIREN attendu
(vide pour les cas où aucun résultat n'est la bonne réponse : hors France,
homonymie non résoluble, entreprise inexistante).

La précision est rapportée globalement ET par type de cas — jamais un
seul chiffre agrégé qui masquerait que certains types de cas (ex. noms
homonymes) ont une précision structurellement plus faible. Conforme au
principe du sujet : "calculer et afficher la couverture par section, sans
jamais masquer un trou" (section 5), appliqué ici à la précision plutôt
qu'à la couverture.

Usage :
    python scripts/mesurer_precision_resolution.py
"""
import csv
import sys

sys.path.append(".")

from scripts.resolution_identite import resoudre
from db.connection import get_engine

CHEMIN_JEU_TEST = "tests/donnees/jeu_test_resolution_identite.csv"


def _charger_jeu_test() -> list[dict]:
    with open(CHEMIN_JEU_TEST, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _evaluer_cas(cas: dict, connexion) -> dict:
    identifiant_brut = cas["identifiant_brut"] or None
    nom_brut = cas["nom_brut"] or None
    siren_attendu = cas["siren_attendu"] or None

    # avec_historique_sirene=True : ce jeu de test n'a pas de contexte
    # acheteur (niveau 4a, continuité, inapplicable ici), mais peut
    # bénéficier du niveau 4b (historique SIRENE) sur les cas où le niveau 3
    # échoue ou est ambigu — notamment les cas 'ambigu' (homonymie) et
    # 'impossible*' ci-dessous, sans jamais fabriquer un résultat (vérifié :
    # le niveau 4b exclut les homonymes courants, cf.
    # scripts/agent_investigation_identite.py).
    resultats = resoudre(identifiant_brut, nom_brut, connexion, avec_historique_sirene=True)

    if siren_attendu is None:
        # Le bon comportement est de NE RIEN trouver (ou de déclarer
        # étranger sans SIREN français) — un résultat français ici serait
        # un faux positif, plus grave qu'un échec honnête.
        correct = len(resultats) == 0 or all(r.get("siren") is None for r in resultats)
    else:
        sirens_trouves = {r["siren"] for r in resultats if r.get("siren")}
        correct = siren_attendu in sirens_trouves

    return {
        "type_cas": cas["type_cas"],
        "correct": correct,
        "resultats": resultats,
        "attendu": siren_attendu,
    }


def mesurer_precision():
    jeu_test = _charger_jeu_test()
    engine = get_engine()

    evaluations = []
    with engine.connect() as connexion:
        for cas in jeu_test:
            evaluations.append(_evaluer_cas(cas, connexion))

    par_type: dict[str, list[bool]] = {}
    for e in evaluations:
        par_type.setdefault(e["type_cas"], []).append(e["correct"])

    print("=" * 72)
    print("PRÉCISION DE LA RÉSOLUTION D'IDENTITÉ — jeu de test annoté")
    print("=" * 72)
    for type_cas, resultats in par_type.items():
        nb_corrects = sum(resultats)
        print(f"{type_cas:40s} {nb_corrects}/{len(resultats)} "
              f"({nb_corrects / len(resultats):.0%})")

    nb_total_correct = sum(e["correct"] for e in evaluations)
    precision_globale = nb_total_correct / len(evaluations)

    # Niveau 2 (normalisation, déterministe) vs niveau 3 (flou,
    # probabiliste) séparément : le sujet ne fixe pas la même certitude
    # aux deux, la précision globale seule le masquerait.
    types_niveau2 = [t for t in par_type if t.startswith("niveau2_")]
    types_niveau3 = [t for t in par_type if "niveau3_" in t or t.startswith("impossible")]
    corrects_n2 = sum(sum(par_type[t]) for t in types_niveau2)
    total_n2 = sum(len(par_type[t]) for t in types_niveau2)
    corrects_n3 = sum(sum(par_type[t]) for t in types_niveau3)
    total_n3 = sum(len(par_type[t]) for t in types_niveau3)

    print("-" * 72)
    if total_n2:
        print(f"Niveau 2 (normalisation, déterministe) : {corrects_n2}/{total_n2} "
              f"({corrects_n2 / total_n2:.0%})")
    if total_n3:
        print(f"Niveau 3 (rapprochement flou, probabiliste) : {corrects_n3}/{total_n3} "
              f"({corrects_n3 / total_n3:.0%})")
    print(f"Précision globale : {nb_total_correct}/{len(evaluations)} ({precision_globale:.0%})")
    print("Cible du sujet (section 8, France) : > 90%")

    # Les cas 'ambigu' (homonymie réelle : plusieurs entreprises françaises
    # partagent exactement la même dénomination) restent, même avec le
    # niveau 4 actif (avec_historique_sirene=True ci-dessus), partiellement
    # non résolubles par le nom seul : le niveau 4a (continuité de marché)
    # est inapplicable dans ce jeu de test isolé (pas de contexte acheteur),
    # et le niveau 4b (historique SIRENE) ne peut désambiguïser que les cas
    # où un seul candidat a une période passée exactement correspondante.
    # Les compter dans la même moyenne que le reste masquerait où se situe
    # vraiment la limite.
    types_hors_perimetre = [t for t in par_type if "ambigu" in t]
    if types_hors_perimetre:
        exclus = sum(len(par_type[t]) for t in types_hors_perimetre)
        corrects_sans_ambigu = nb_total_correct - sum(sum(par_type[t]) for t in types_hors_perimetre)
        total_sans_ambigu = len(evaluations) - exclus
        print(f"Précision hors homonymie (niveau 4 actif, résiduellement indécidable pour une partie des cas) : "
              f"{corrects_sans_ambigu}/{total_sans_ambigu} "
              f"({corrects_sans_ambigu / total_sans_ambigu:.0%})")

    if precision_globale < 0.90:
        print("⚠️  Cible globale non atteinte — documenté tel quel, pas masqué. "
              "Cause principale : homonymie de dénomination (cas 'ambigu'). Le niveau 4 "
              "(agent d'investigation d'identité, actif dans cette mesure) en résout une "
              "partie légitimement (continuité de marché ou historique de dénomination) ; "
              "le reste demeure structurellement indécidable par le nom seul sans contexte "
              "acheteur ni historique de renommage exploitable.")
    print("=" * 72)

    return precision_globale


if __name__ == "__main__":
    mesurer_precision()
