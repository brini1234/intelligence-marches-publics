"""
Mesure la précision de détection du sortant (sujet, section 8 : "Précision
de détection du sortant | mesurée sur cas connus") contre un jeu de cas
réels annotés à la main (tests/donnees/jeu_test_detecter_sortant.csv),
même méthodologie que scripts/mesurer_precision_resolution.py : vérité
terrain établie en lisant directement l'historique brut des attributions
(nom, date, montant) et en jugeant ce qu'un humain conclurait, jamais une
donnée inventée.

Deux métriques distinctes, jamais mélangées dans un seul chiffre :
    - précision du SIREN du sortant (métrique primaire, celle citée par le
      sujet) : sortant_probable correspond au SIREN attendu. Un seul cas
      (type_cas="sans_historique") attend explicitement l'absence de
      sortant (aucun marché en base) ; le cas ambigu
      (type_cas="cas_ambigu_multi_titulaires") est volontairement EXCLU de
      cette métrique plutôt que de forcer une fausse attente : par design,
      detecter_sortant() retourne toujours un meilleur candidat avec une
      confiance dégradée plutôt que de refuser de répondre (cohérent avec
      le reste du projet — jamais "aucune réponse", toujours "une réponse
      avec son incertitude signalée") ; exiger `siren_sortant is None`
      sur ce cas serait tester un comportement que le code n'a jamais eu
      vocation à avoir.
    - concordance du niveau de confiance (informative, secondaire, jamais
      comptée dans la précision ci-dessus) : deux cas réels (CHU Toulouse,
      Région Normandie) documentent un écart connu et assumé - un
      titulaire unique et stable peut recevoir une confiance "faible"
      quand les contrats se chevauchent dans le temps, une limite de
      l'heuristique de cohérence temporelle (cf. detecter_sortant.py),
      pas une erreur de détection du sortant lui-même.

Usage :
    python scripts/mesurer_precision_sortant.py
"""
import csv
import sys

sys.path.append(".")

from scripts.detecter_sortant import detecter_sortant

CHEMIN_JEU_TEST = "tests/donnees/jeu_test_detecter_sortant.csv"


def _charger_jeu_test() -> list[dict]:
    with open(CHEMIN_JEU_TEST, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _evaluer_cas(cas: dict) -> dict:
    siren_attendu = cas["siren_sortant_attendu"] or None
    confiance_attendue = cas["confiance_attendue"] or None
    exclu_de_la_precision = cas["type_cas"] == "cas_ambigu_multi_titulaires"

    resultat = detecter_sortant(cas["siret_acheteur"], cas["code_cpv"])

    if exclu_de_la_precision:
        correct = None  # non évalué sur le SIREN, seulement sur la confiance ci-dessous
    elif siren_attendu is None:
        # Seul le cas "sans_historique" (aucun marché en base) attend
        # explicitement l'absence de sortant.
        correct = resultat.get("siren_sortant") is None
    else:
        correct = resultat.get("siren_sortant") == siren_attendu

    confiance_ok = confiance_attendue is None or resultat["confiance"] == confiance_attendue

    return {
        "type_cas": cas["type_cas"],
        "nom_acheteur": cas["nom_acheteur"],
        "correct": correct,
        "confiance_obtenue": resultat["confiance"],
        "confiance_attendue": confiance_attendue,
        "confiance_ok": confiance_ok,
        "commentaire": cas["commentaire"],
    }


def mesurer_precision():
    jeu_test = _charger_jeu_test()
    evaluations = [_evaluer_cas(cas) for cas in jeu_test]

    print("=" * 72)
    print("PRÉCISION DE DÉTECTION DU SORTANT — jeu de cas connus")
    print("=" * 72)
    for e in evaluations:
        statut = "⚪ (exclu)" if e["correct"] is None else ("✅" if e["correct"] else "❌")
        concordance = "=" if e["confiance_ok"] else "≠"
        print(f"{statut} {e['type_cas']:28s} {e['nom_acheteur'][:40]:40s} "
              f"| confiance {e['confiance_obtenue']:8s} {concordance} attendue={e['confiance_attendue']}")
        if e["correct"] is None:
            print(f"     exclu de la précision SIREN (structurellement indécidable) : {e['commentaire']}")
        elif not e["confiance_ok"]:
            print(f"     écart de confiance assumé et documenté : {e['commentaire']}")

    evaluees = [e for e in evaluations if e["correct"] is not None]
    nb_corrects = sum(e["correct"] for e in evaluees)
    # Division par zéro évitée explicitement : si le jeu de test grandit un
    # jour avec plus de cas exclus (ambigus) que de cas évaluables, il ne
    # doit jamais planter — un jeu de test entièrement exclu est une
    # anomalie de configuration à signaler, pas une exception non gérée.
    precision = (nb_corrects / len(evaluees)) if evaluees else None
    nb_confiance_ok = sum(e["confiance_ok"] for e in evaluations)

    print("-" * 72)
    if precision is None:
        print("Précision du SIREN du sortant : non calculable — tous les cas du jeu de "
              "test sont exclus (structurellement indécidables). Vérifier tests/donnees/"
              "jeu_test_detecter_sortant.csv.")
    else:
        print(f"Précision du SIREN du sortant (métrique du sujet, section 8) : "
              f"{nb_corrects}/{len(evaluees)} ({precision:.0%}) "
              f"— {len(evaluations) - len(evaluees)} cas exclu(s) car structurellement indécidable(s)")
    print(f"Concordance du niveau de confiance (informatif, non compté ci-dessus) : "
          f"{nb_confiance_ok}/{len(evaluations)}")
    print("Le sujet ne fixe pas de seuil chiffré pour cette métrique (contrairement à "
          "la résolution d'identité, cible >90%) — seulement \"mesurée sur cas connus\".")
    print("=" * 72)

    return precision


if __name__ == "__main__":
    mesurer_precision()
