"""
Agent "Investigation d'identité" (sujet, section 4 : niveau 4 de la
hiérarchie de résolution d'identité, section 5 — "quand le SIRET manque et
que le rapprochement est ambigu, l'agent enquête (SIRENE, structure de
groupe, site de l'entreprise)"). Le sujet le qualifie de "le plus rentable
des trois, car l'identité est le principal risque qualité".

Deux mécanismes réels, sans passerelle LLM ni recherche web générique
(l'agent d'enrichissement web, niveau 5, est un agent séparé et implémenté
lui aussi — scripts/agent_enrichissement_web.py, dernier recours après
échec des niveaux 1-4, cf. README) :
    - continuité de marché (niveau 4a) : implémentée directement dans
      scripts/resolution_identite.py (resoudre_par_continuite_acheteur),
      purement SQL, utilisée en direct pendant transformer_silver_marches.py
      — quand le niveau 3 est ambigu (homonymie), un acheteur qui a déjà
      attribué un marché à l'un des candidats devient le signal de
      désambiguïsation.
    - historique de dénomination via l'API SIRENE (niveau 4b, ce module) :
      quand le niveau 3 échoue totalement (le nom cherché n'existe dans
      aucun candidat courant du stock national), interroge l'historique des
      dénominations de l'unité légale (opérateur periode() de l'API
      v3.11) — couvre le piège "changement de raison sociale" (sujet,
      section 8) pour un vrai renommage d'entreprise (même SIREN), pas une
      fusion/scission. Vérifié en direct sur un cas réel : SIREN 380129866,
      "FRANCE TELECOM" jusqu'au 2013-06-30 puis "ORANGE" depuis
      (changementDenominationUniteLegale=true sur cette période).

Ce script, exécuté seul, traite le résidu réel de silver_marches
(acheteurs toujours sans SIRET après les niveaux 1-3, avec un nom
exploitable) via l'historique SIRENE — rate-limited, même délai que
scripts/completer_via_api_sirene.py, sur le même modèle : sélection
automatique du résidu par SQL, jamais de sélection manuelle.

Limite assumée : ne couvre que les acheteurs, pas les titulaires. Les
titulaires non résolus par les niveaux 1-3 ne sont, par construction de
transformer_silver_marches.py, jamais insérés dans silver_attributions
(seuls les SIRET valides y sont conservés) : il n'existe pas de résidu
titulaire directement requêtable sans revenir à bronze_*. Hors périmètre de
cette livraison.

Usage :
    python scripts/agent_investigation_identite.py
"""
import sys
import time

sys.path.append(".")

from sqlalchemy import text

from connectors.sirene import rechercher_par_denomination_historique
from db.connection import get_engine
from scripts.resolution_identite import normaliser_nom, resoudre_siren_vers_siret_siege

DELAI_ENTRE_APPELS_SECONDES = 2.0  # même limite constatée que completer_via_api_sirene.py


def investiguer_via_historique_sirene(nom_brut: str, connexion=None) -> dict | None:
    """
    Niveau 4b : cherche dans l'historique des dénominations SIRENE (API,
    opérateur periode()) un SIREN dont une dénomination PASSÉE correspond
    exactement (après normalisation) au nom cherché.

    Point critique découvert en vérifiant ce mécanisme sur un cas réel
    (FRANCE TELECOM -> ORANGE, SIREN 380129866) : ne compter QUE les
    périodes passées (dateFin renseignée), jamais la période courante
    (dateFin NULL). Sinon, un homonyme ACTUEL sans rapport (ex. SIREN
    441965027, une petite entreprise réellement nommée "FRANCE TELECOM"
    aujourd'hui, sans lien avec l'ex-France Télécom/Orange) serait compté
    comme une correspondance — un vrai homonyme courant n'est pas un
    changement de raison sociale. Ce filtre est ce qui rend le mécanisme
    fiable : vérifié en direct, seul le SIREN 380129866 a une période
    PASSÉE exactement "FRANCE TELECOM" ; le SIREN 441965027 ne matche que
    sur sa période courante et est donc exclu.

    Si plusieurs SIREN distincts ont une période passée exactement
    correspondante (ambiguïté), ne retourne rien plutôt qu'un pick
    arbitraire — même principe que resoudre_par_similarite pour
    l'homonymie.

    Dégradation gracieuse : toute erreur réseau/quota/clé absente renvoie
    None, jamais de crash (même principe que completer_via_api_sirene.py).
    """
    nom_normalise = normaliser_nom(nom_brut)
    if not nom_normalise:
        return None

    try:
        candidats = rechercher_par_denomination_historique(nom_brut)
    except Exception:
        return None

    correspondances = set()
    for candidat in candidats:
        for periode in candidat.get("periodesUniteLegale") or []:
            if periode.get("dateFin") is None:
                continue  # période courante : un homonyme actuel n'est pas un changement de nom
            if normaliser_nom(periode.get("denominationUniteLegale") or "") == nom_normalise:
                correspondances.add(candidat.get("siren"))
                break

    if len(correspondances) != 1:
        return None  # aucune correspondance historique exacte, ou ambiguïté -> doute signalé, pas de pick

    siren = correspondances.pop()
    siret = resoudre_siren_vers_siret_siege(siren, connexion) if connexion is not None else None

    return {
        "siret": siret,
        "siren": siren,
        "methode": "investigation_historique_denomination",
        "score_confiance": 0.8,
    }


def _acheteurs_a_investiguer(connexion) -> list[dict]:
    """Sélection automatique du résidu réel : acheteurs encore sans SIRET
    résolu après niveaux 1-3, avec un nom exploitable. Jamais de sélection
    manuelle (même principe que completer_via_api_sirene.py)."""
    lignes = connexion.execute(text("""
        SELECT DISTINCT uid, nom_acheteur FROM silver_marches
        WHERE siret_acheteur IS NULL AND nom_acheteur IS NOT NULL AND nom_acheteur <> ''
    """)).fetchall()
    return [{"uid": uid, "nom": nom} for uid, nom in lignes]


def investiguer_identite():
    engine = get_engine()
    with engine.connect() as connexion:
        residu = _acheteurs_a_investiguer(connexion)

    if not residu:
        print("Aucun résidu à investiguer (tout est déjà résolu par les niveaux 1-3).")
        return

    print(f"{len(residu)} acheteur(s) à investiguer via l'historique SIRENE "
          f"(~{len(residu) * DELAI_ENTRE_APPELS_SECONDES:.0f}s estimées) ...")

    resolus = 0
    for i, cas in enumerate(residu, start=1):
        with engine.begin() as connexion:
            resultat = investiguer_via_historique_sirene(cas["nom"], connexion)
            if resultat and resultat["siret"]:
                connexion.execute(text("""
                    UPDATE silver_marches
                    SET siret_acheteur = :siret, methode_resolution_acheteur = :methode,
                        score_confiance_acheteur = :score
                    WHERE uid = :uid AND siret_acheteur IS NULL
                """), {
                    "siret": resultat["siret"], "methode": resultat["methode"],
                    "score": resultat["score_confiance"], "uid": cas["uid"],
                })
                resolus += 1
                print(f"  [{i}/{len(residu)}] {cas['nom']!r} -> résolu (SIREN {resultat['siren']}, "
                      f"changement de raison sociale)")

        if i % 20 == 0:
            print(f"  ... {i}/{len(residu)} traités")

        time.sleep(DELAI_ENTRE_APPELS_SECONDES)

    print(f"\n✅ Investigation terminée : {resolus}/{len(residu)} résolu(s) via l'historique de "
          f"dénomination. Le reste n'est pas un cas de changement de raison sociale identifiable "
          f"par ce mécanisme (identifiant mal saisi, structure non-SIRENE, etc.) — non résolu "
          f"honnêtement plutôt que deviné.")


if __name__ == "__main__":
    investiguer_identite()
