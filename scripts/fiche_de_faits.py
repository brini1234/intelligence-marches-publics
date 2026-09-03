import sys
sys.path.append(".")

from collections import Counter

from db.connection import get_engine
from scripts.detecter_sortant import detecter_sortant
from scripts.agent_expansion_couverture import (
    agent_expansion_couverture,
    construire_message_centrale_achat,
    detecter_centrale_achat,
    SEUIL_COUVERTURE_SUFFISANTE,
)
from scripts.schemas import FicheDeFaits

SCORES_COUVERTURE = {
    "élevée": 1.0,
    "moyenne": 0.66,
    "faible": 0.33,
    "aucune": 0.0,
}

# Piège du sujet (section 8) : "Concurrent hors France -> score de confiance
# dégradé et déclaré". Un concurrent hors France ne peut pas être vérifié via
# le référentiel SIRENE (identité, activité, existence légale) : sa présence
# dégrade donc la confiance qu'on peut avoir sur la liste des concurrents,
# même si le sortant lui-même reste bien identifié.
COUVERTURE_MAX_SI_CONCURRENT_ETRANGER = 0.33  # plafonnée à "faible", jamais mieux


def _valider(fiche: dict) -> dict:
    """
    Sortie structurée, validation systématique (sujet, section 9 :
    "Pydantic et JSON Schéma, validation systématique") : chaque fiche de
    faits produite par construire_fiche_de_faits() passe par
    scripts.schemas.FicheDeFaits avant d'être renvoyée à l'appelant — une
    valeur de type inattendu, une couverture hors [0,1] ou une provenance
    vide lève une erreur de validation ici, immédiatement, plutôt que de se
    propager silencieusement jusqu'au texte verbalisé.

    Correctif du 02/09/2026 : `exclude_none=True` sur le dump global
    supprimait aussi la clé "valeur" de tout `Fait` dont la valeur est
    légitimement `None` (ex. `fourchette_prix_min`/`max` sans montant
    publié sur la famille) — pas seulement "raison"/"marches_support" au
    niveau racine. `scripts/bloc_de_decision.py` accède à
    `valeurs["fourchette_prix_min"]["valeur"]` sans `.get()` : la clé
    manquante levait un `KeyError` en production sur tout acheteur/CPV
    réel sans aucun montant publié (cas vérifié en base, ex.
    siret_acheteur="26750004902888", code_cpv="72250000") — un plantage du
    point d'entrée principal du produit. `exclude_none` ne s'applique donc
    plus qu'aux deux champs racine réellement optionnels.
    """
    dump = FicheDeFaits(**fiche).model_dump(mode="json")
    for cle in ("raison", "marches_support"):
        if dump.get(cle) is None:
            dump.pop(cle, None)
    return dump


def construire_fiche_de_faits(siret_acheteur: str, code_cpv: str) -> dict:
    """
    Transforme un résultat de détection du sortant en fiche de faits JSON,
    conforme au bloc de décision exigé : sortant, concurrents, fourchette de
    prix, pondération de l'acheteur (non couverte), couverture globale.
    """
    # Piège du sujet (section 8) : "marché passé par une centrale d'achat ->
    # limite de couverture signalée". Vérifié EN PREMIER et INCONDITIONNELLEMENT
    # (pas seulement quand la couverture est faible) : la limite tient à
    # l'identité de l'acheteur (le SIRET en base est celui de la centrale,
    # jamais de l'organisme bénéficiaire réel), pas au volume de marchés
    # retrouvés sous ce SIRET. Une centrale comme l'UGAP a typiquement BEAUCOUP
    # de marchés — la gater derrière un seuil de couverture faible la aurait
    # rendue muette sur le cas courant et ne se serait déclenchée que par
    # coïncidence, jamais correctement pour ce piège précis.
    engine = get_engine()
    with engine.connect() as connexion:
        centrale = detecter_centrale_achat(siret_acheteur, connexion)
    if centrale is not None:
        return _valider({
            "faits": [],
            "couverture_globale": 0.0,
            "raison": construire_message_centrale_achat(centrale),
        })

    resultat = detecter_sortant(siret_acheteur, code_cpv)
    expansions_appliquees: list[dict] = []

    # Agent "Expansion pilotée par la couverture" (sujet, section 4 et 6, S6 :
    # scripts/agent_expansion_couverture.py) : déclenché uniquement quand la
    # requête directe est pauvre (couverture insuffisante) — jamais sur un
    # résultat déjà satisfaisant, pour ne pas alourdir le cas courant.
    if resultat.get("nb_marches_famille", 0) < SEUIL_COUVERTURE_SUFFISANTE:
        expansion = agent_expansion_couverture(siret_acheteur, code_cpv)

        if expansion["type"] == "donnees_insuffisantes":
            return _valider({
                "faits": [],
                "couverture_globale": 0.0,
                "raison": expansion["message"],
            })

        resultat = expansion["resultat_sortant"]
        expansions_appliquees = expansion["expansions_appliquees"]

    score = SCORES_COUVERTURE.get(resultat["confiance"], 0.0)

    if resultat["sortant_probable"] is None:
        return _valider({
            "faits": [],
            "couverture_globale": 0.0,
            "raison": resultat["raison"],
        })

    historique = resultat["historique"]

    # Couverture de l'échéance estimée (sujet section 4 : "estimer la date
    # d'expiration à partir de la date d'attribution et de la durée
    # (inférée par famille de marché quand elle manque)") : une durée
    # réellement publiée par la source garde la couverture normale du
    # sortant ; une durée inférée par médiane CPV dégrade la couverture
    # (c'est une estimation, jamais aussi certaine qu'une donnée source) ;
    # aucune durée disponible nulle part sur ce CPV -> couverture nulle,
    # jamais un chiffre fabriqué.
    duree_source = resultat.get("duree_source")
    if duree_source == "reelle":
        couverture_expiration = score
    elif duree_source == "inferee_famille_cpv":
        couverture_expiration = round(score * 0.5, 2)
    else:
        couverture_expiration = 0.0

    # Concurrents observés : les autres entreprises de la même famille de
    # marchés, hors le sortant actuel, sans doublon, dans l'ordre d'apparition.
    # Chaque concurrent porte sa fréquence d'apparition sur l'ensemble des
    # attributions retrouvées pour cet acheteur/CPV — formulation exigée par
    # le sujet (section 2) : jamais une "part de marché" en %, toujours un
    # compte brut ("X apparaît dans N des M attributions retrouvées"), qui
    # ne prétend pas être une part de marché faute d'univers exhaustif connu.
    # Les concurrents hors France sont explicitement étiquetés dans leur nom
    # (déclaration visible dans le texte final, pas seulement dans un champ
    # technique que personne ne lit).
    total_attributions = len(historique)
    occurrences = Counter()
    hors_france = set()
    ordre_apparition = []
    for h in historique:
        nom = h["denomination"]
        if nom is None or nom == resultat["sortant_probable"]:
            continue
        if nom not in occurrences:
            ordre_apparition.append(nom)
        occurrences[nom] += 1
        if h.get("etat_administratif") == "ETRANGER":
            hors_france.add(nom)

    concurrents = []
    nb_concurrents_hors_france = 0
    for nom in ordre_apparition:
        frequence = f"{occurrences[nom]}/{total_attributions} attribution(s)"
        if nom in hors_france:
            concurrents.append(f"{nom} [hors France] ({frequence})")
            nb_concurrents_hors_france += 1
        else:
            concurrents.append(f"{nom} ({frequence})")

    # Fourchette de prix observée sur toute la famille de marchés. Aucun
    # montant publié sur toute la famille (ex. marchés TED sans montant
    # renseigné) -> couverture nulle, jamais un chiffre fabriqué ni une
    # couverture non nulle sur une valeur absente (même principe que
    # couverture_expiration ci-dessus).
    montants = [h["montant"] for h in historique if h["montant"] is not None]
    prix_min = min(montants) if montants else None
    prix_max = max(montants) if montants else None
    couverture_prix = score if montants else 0.0

    # Couverture du fait "concurrents_observes" : dégradée si au moins un
    # concurrent hors France est présent, car son identité/activité n'a pas
    # pu être vérifiée via SIRENE (référentiel France uniquement).
    couverture_concurrents = score if resultat["nb_marches_famille"] > 1 else 0.0
    if nb_concurrents_hors_france > 0:
        couverture_concurrents = min(couverture_concurrents, COUVERTURE_MAX_SI_CONCURRENT_ETRANGER)

    faits = [
        {
            "cle": "titulaire_actuel",
            "valeur": resultat["sortant_probable"],
            "provenance": "table entreprises, via jointure attributions/marches",
            "couverture": score,
        },
        {
            "cle": "duree_restante_mois",
            "valeur": resultat["duree_restante_mois"],
            "provenance": "table marches, champ duree_restante_mois (source DECP)",
            # Champ absent par construction pour tout marché TED (jamais
            # publié à ce niveau, cf. README) : couverture nulle plutôt que
            # `score`, même principe que couverture_expiration ci-dessous —
            # sinon un fait sans valeur gonflerait couverture_globale
            # (moyenne des couvertures) sans qu'aucune section affichée ne
            # le laisse deviner. Correctif du 02/09/2026.
            "couverture": score if resultat.get("duree_restante_mois") is not None else 0.0,
        },
        {
            "cle": "date_expiration_estimee",
            "valeur": resultat.get("date_expiration_estimee") or "inconnue",
            "provenance": (
                "calculé : date_notification + durée réelle (table marches)"
                if duree_source == "reelle"
                else "calculé : date_notification + durée médiane observée sur ce CPV "
                     "(durée réelle absente de la source, notamment tous les marchés TED)"
                if duree_source == "inferee_famille_cpv"
                else "non calculable : aucune durée, réelle ou inférable, disponible pour ce CPV"
            ),
            "couverture": couverture_expiration,
        },
        {
            "cle": "date_dernier_marche",
            "valeur": resultat["date_notification"],
            "provenance": "table marches, champ date_notification",
            "couverture": score,
        },
        {
            "cle": "nombre_marches_historique",
            "valeur": resultat["nb_marches_famille"],
            "provenance": "COUNT sur marches filtré par acheteur et code_cpv",
            "couverture": score,
        },
        {
            "cle": "concurrents_observes",
            "valeur": concurrents if concurrents else "aucun autre concurrent observé",
            "provenance": "table attributions, entreprises distinctes hors sortant sur la même famille CPV",
            "couverture": couverture_concurrents,
        },
        {
            "cle": "fourchette_prix_min",
            "valeur": prix_min,
            "provenance": "MIN(montant) sur marches de la même famille",
            "couverture": couverture_prix,
        },
        {
            "cle": "fourchette_prix_max",
            "valeur": prix_max,
            "provenance": "MAX(montant) sur marches de la même famille",
            "couverture": couverture_prix,
        },
        {
            "cle": "ponderation_acheteur",
            "valeur": "non disponible",
            "provenance": "aucune source connectée ne publie les critères de pondération prix/technique",
            "couverture": 0.0,
        },
    ]

    # Trace de l'agent d'expansion (sujet, section 8 : le harnais doit pouvoir
    # vérifier que l'élargissement a bien eu lieu sans parser le texte final).
    # Couverture volontairement dégradée (0.5, même principe que
    # couverture_expiration inférée par médiane CPV) : le résultat repose sur
    # un périmètre plus large que l'acheteur/CPV exact demandé, donc moins
    # spécifique, jamais présenté avec la même certitude qu'une requête directe.
    if expansions_appliquees:
        faits.append({
            "cle": "elargissement_applique",
            "valeur": "; ".join(f"{e['axe']}: {e['valeur']}" for e in expansions_appliquees),
            "provenance": "agent d'expansion pilotée par la couverture (scripts/agent_expansion_couverture.py)",
            "couverture": 0.5,
        })

    # Fait explicite (compté, jamais approximé) pour la déclaration exigée par
    # le sujet et pour que le harnais puisse vérifier automatiquement que le
    # piège est bien couvert, sans avoir à parser le texte du concurrent.
    if nb_concurrents_hors_france > 0:
        faits.append({
            "cle": "nb_concurrents_hors_france",
            "valeur": nb_concurrents_hors_france,
            "provenance": "table entreprises, champ etat_administratif = 'ETRANGER'",
            "couverture": 1.0,  # fait certain : soit on l'a compté, soit il n'existe pas
        })

    # Couverture globale : moyenne des couvertures de tous les faits (honnête,
    # pas juste le meilleur cas)
    couverture_globale = sum(f["couverture"] for f in faits) / len(faits)

    return _valider({
        "faits": faits,
        "couverture_globale": round(couverture_globale, 2),
        "marches_support": resultat["marches_support"],
    })


if __name__ == "__main__":
    import json
    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    print(json.dumps(fiche, indent=2, ensure_ascii=False, default=str))
