"""
Complète via l'API SIRENE les entreprises qui restent sans données après
l'import en masse + le nettoyage.

Pourquoi un résidu existe malgré un import "complet" : le fichier stock est
une photo du répertoire datée du dernier jour du mois précédent (voir data.gouv.fr).
Une entreprise créée après cette date, ou dont le SIRET a été mal saisi dans
DECP, n'apparaîtra jamais dans le stock avant le prochain import mensuel.
L'API Sirene, elle, est mise à jour quotidiennement — donc utilisée ici
uniquement comme rattrapage sur un petit résidu, jamais comme méthode
principale (ce serait revenir à l'ancien import manuel entreprise par
entreprise que ce script remplace).

Ce script :
    - identifie automatiquement (par SQL) les entreprises encore incomplètes,
      sans sélection manuelle
    - interroge l'API une fois par entreprise manquante, avec un délai entre
      appels pour respecter le quota
    - marque explicitement les échecs (SIREN inexistant, radié sans succession,
      erreur API) pour ne jamais les requêter en boucle inutilement

Usage :
    python scripts/completer_via_api_sirene.py
"""
import re
import sys
import time

sys.path.append(".")

from sqlalchemy import text

from connectors.sirene import AccesRestreintSirene, recuperer_entreprise_par_siren
from db.connection import get_engine

DELAI_ENTRE_APPELS_SECONDES = 2.0  # 30 req/min : 0.5s dépassait la limite réelle de l'API Sirene (429 en pratique)

# Un vrai SIREN est exactement 9 chiffres. Tout ce qui ne matche pas ce format
# n'a aucune chance d'exister dans l'API Sirene française — inutile de
# gaspiller un appel API dessus, et surtout inutile de le retenter en boucle
# à chaque exécution du script.
REGEX_SIREN_VALIDE = re.compile(r"^\d{9}$")

# Piège explicitement cité par le sujet (section 8) : "Concurrent hors France
# -> score de confiance dégradé et déclaré". Les identifiants DECP de
# titulaires étrangers commencent typiquement par un code pays ISO à 2 lettres
# (SE, NL, BE...) suivi de chiffres, ou par un numéro de TVA intracommunautaire
# français mal extrait (FRxx + SIREN, parfois tronqué à l'import).
REGEX_IDENTIFIANT_ETRANGER = re.compile(r"^[A-Z]{2}")


def _recuperer_entreprises_incompletes(connexion) -> list[dict]:
    """
    Sélection automatique : toute entreprise sans code NAF connu ET pas déjà
    marquée comme introuvable lors d'une tentative précédente.
    """
    lignes = connexion.execute(text("""
        SELECT siren FROM entreprises
        WHERE code_naf IS NULL
          AND COALESCE(etat_administratif, '') NOT IN
              ('INTROUVABLE_API', 'ETRANGER', 'SIREN_MALFORME', 'NON_DIFFUSIBLE')
    """)).fetchall()
    return [row[0] for row in lignes]


def _appliquer_reponse_api(connexion, siren: str, donnees: dict | None) -> str:
    if donnees is None:
        connexion.execute(text("""
            UPDATE entreprises SET etat_administratif = 'INTROUVABLE_API'
            WHERE siren = :siren
        """), {"siren": siren})
        return "introuvable"

    unite_legale = donnees.get("uniteLegale", {})
    # Pour certains types d'entités (associations, GIE...), l'API Sirene ne
    # renseigne denominationUniteLegale/categorieJuridiqueUniteLegale/
    # activitePrincipaleUniteLegale/etatAdministratifUniteLegale qu'à
    # l'intérieur de la période courante, pas au niveau racine de
    # uniteLegale. periodesUniteLegale[0] est la période la plus récente.
    periodes = unite_legale.get("periodesUniteLegale") or []
    periode_courante = periodes[0] if periodes else {}

    def _champ(nom: str):
        return unite_legale.get(nom) or periode_courante.get(nom)

    etat_administratif = _champ("etatAdministratifUniteLegale")
    connexion.execute(text("""
        UPDATE entreprises SET
            raison_sociale_legale = COALESCE(:denomination, raison_sociale_legale),
            denomination = CASE
                WHEN denomination IS NULL OR denomination = 'Inconnu'
                THEN COALESCE(:denomination, denomination)
                ELSE denomination
            END,
            forme_juridique = :forme_juridique,
            code_naf = :code_naf,
            etat_administratif = :etat_administratif,
            est_active = :est_active
        WHERE siren = :siren
    """), {
        "siren": siren,
        "denomination": _champ("denominationUniteLegale"),
        "forme_juridique": _champ("categorieJuridiqueUniteLegale"),
        "code_naf": _champ("activitePrincipaleUniteLegale"),
        "etat_administratif": etat_administratif,
        "est_active": etat_administratif == "A",
    })
    return "complété"


def completer_via_api_sirene():
    engine = get_engine()

    with engine.begin() as connexion:
        sirens_incomplets = _recuperer_entreprises_incompletes(connexion)

    if not sirens_incomplets:
        print("Aucune entreprise incomplète — rien à faire via l'API.")
        return

    # Tri préalable : on ne gaspille pas d'appel API sur ce qui ne peut
    # structurellement pas être un SIREN français.
    sirens_valides = [s for s in sirens_incomplets if REGEX_SIREN_VALIDE.match(s)]
    identifiants_etrangers = [s for s in sirens_incomplets if REGEX_IDENTIFIANT_ETRANGER.match(s)]
    autres_malformes = [
        s for s in sirens_incomplets
        if s not in sirens_valides and s not in identifiants_etrangers
    ]

    if identifiants_etrangers:
        print(f"{len(identifiants_etrangers)} identifiant(s) hors France détecté(s) "
              f"(titulaire non-français dans DECP) : {identifiants_etrangers}")
        with engine.begin() as connexion:
            connexion.execute(text("""
                UPDATE entreprises SET etat_administratif = 'ETRANGER'
                WHERE siren = ANY(:sirens)
            """), {"sirens": identifiants_etrangers})
        print("  -> marqués 'ETRANGER', ne seront plus retentés via l'API française. "
              "À traiter par le futur agent d'investigation d'identité (source hors SIRENE).")

    if autres_malformes:
        print(f"{len(autres_malformes)} identifiant(s) ni SIREN valide ni format étranger "
              f"reconnu : {autres_malformes}")
        with engine.begin() as connexion:
            connexion.execute(text("""
                UPDATE entreprises SET etat_administratif = 'SIREN_MALFORME'
                WHERE siren = ANY(:sirens)
            """), {"sirens": autres_malformes})
        print("  -> marqués 'SIREN_MALFORME'. À investiguer manuellement : probablement une "
              "erreur de saisie côté source DECP, pas un problème de notre pipeline.")

    if not sirens_valides:
        print("\nAucun SIREN valide restant à interroger via l'API.")
        return

    print(f"\n{len(sirens_valides)} SIREN valide(s) restant(s), "
          f"complément via l'API SIRENE (~{len(sirens_valides) * DELAI_ENTRE_APPELS_SECONDES:.0f}s estimées)")

    compteurs = {"complété": 0, "introuvable": 0, "non_diffusible": 0, "erreur": 0}
    for i, siren in enumerate(sirens_valides, start=1):
        try:
            donnees = recuperer_entreprise_par_siren(siren)
        except AccesRestreintSirene:
            # 403 permanent sur ce SIREN précis (établissement à diffusion
            # restreinte) : ce n'est pas un quota transitoire, retenter ne
            # changera rien -> marqué définitivement, comme INTROUVABLE_API.
            with engine.begin() as connexion:
                connexion.execute(text("""
                    UPDATE entreprises SET etat_administratif = 'NON_DIFFUSIBLE'
                    WHERE siren = :siren
                """), {"siren": siren})
            print(f"  [{i}/{len(sirens_valides)}] {siren} : accès restreint (403, établissement non-diffusible) "
                  f"— marqué définitivement")
            compteurs["non_diffusible"] += 1
            time.sleep(DELAI_ENTRE_APPELS_SECONDES)
            continue
        except Exception as erreur:
            print(f"  [{i}/{len(sirens_valides)}] {siren} : erreur API ({erreur}) — sera retenté au prochain passage")
            compteurs["erreur"] += 1
            time.sleep(DELAI_ENTRE_APPELS_SECONDES)
            continue

        with engine.begin() as connexion:
            resultat = _appliquer_reponse_api(connexion, siren, donnees)
        compteurs[resultat] += 1

        if i % 20 == 0:
            print(f"  ... {i}/{len(sirens_valides)} traités")

        time.sleep(DELAI_ENTRE_APPELS_SECONDES)

    print(f"\n✅ Complément API terminé : {compteurs['complété']} complété(s), "
          f"{compteurs['introuvable']} introuvable(s) (marqué définitivement), "
          f"{compteurs['non_diffusible']} non-diffusible(s) (marqué définitivement), "
          f"{compteurs['erreur']} erreur(s) (à retenter)")


if __name__ == "__main__":
    completer_via_api_sirene()
