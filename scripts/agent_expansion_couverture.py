"""
Agent "Expansion pilotée par la couverture" (sujet, section 4 : un des 3
agents prévus — les deux autres sont aussi implémentés : investigation
d'identité (scripts/agent_investigation_identite.py) et enrichissement web
(scripts/agent_enrichissement_web.py, optionnel selon le sujet, cf. README).

Pas d'appel à un modèle de langage : ce module prend ses décisions (quel axe
élargir, quand s'arrêter) via une procédure déterministe qui interroge la
base, réévalue le résultat, et essaie l'axe suivant si besoin — exactement
ce que demande le sujet ("l'agent décide comment élargir la recherche ...,
réévalue, et sait conclure que les données sont insuffisantes"), sans
passerelle LLM (aucune n'est configurée dans ce projet). Le "jugement" est
dans l'ordre des essais et les seuils d'arrêt, pas dans un texte généré.

Deux comportements couverts (sujet, section 8, pièges de démonstration) :
    - "Marché passé par une centrale d'achat -> limite de couverture
      signalée" : détecté et signalé AVANT toute tentative d'expansion (une
      centrale d'achat porte le marché à son propre SIRET ; élargir la
      recherche ne retrouvera jamais l'organisme bénéficiaire réel, absent
      des données DECP/TED).
    - "Acheteur sans historique -> données insuffisantes" : ce module évite
      simplement de gaspiller des requêtes d'expansion sur un acheteur qui
      n'a structurellement aucun marché en base (déjà détecté par
      detecter_sortant() seul).

Axes d'expansion essayés dans l'ordre (sujet section 4 : "acheteurs
comparables, périmètre géographique, CPV parent, fenêtre temporelle") :
    1. CPV parent (ex. 72220000 -> 722200 -> 7222 -> 72) : seul axe qui peut
       changer le sortant retourné lui-même (les 3 autres n'élargissent que
       les statistiques de prix/concurrents autour d'un sortant déjà connu
       ou absent).
    2. Acheteurs comparables, même NAF + même département (référentiel
       SIRENE national — déjà joignable pour 99% des acheteurs de la base).
    3. Périmètre géographique élargi : mêmes acheteurs comparables, NAF
       identique mais sans restriction de département (national) — c'est
       littéralement l'axe "géographique" du sujet, appliqué en relâchant
       la contrainte de zone plutôt qu'en la resserrant.
    4. Fenêtre temporelle : structurellement un no-op ici. detecter_sortant()
       n'applique déjà aucun filtre de date (il regarde tout l'historique
       disponible pour l'acheteur/CPV) ; la vraie limite est en amont, à
       l'ingestion (fenêtre fixe de 3 ans, cf. README). L'agent le constate
       et le déclare explicitement plutôt que de simuler un élargissement
       qui ne changerait rien.
"""
import sys

sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine
from scripts.detecter_sortant import detecter_sortant

SEUIL_COUVERTURE_SUFFISANTE = 2  # nb_marches_famille en dessous duquel l'expansion est déclenchée
CPV_LONGUEURS_PARENT = [6, 4, 2]  # ex. 72220000 -> 722200 -> 7222 -> 72

# Noms connus de centrales d'achat françaises (sujet, glossaire section 11 :
# "organisme achetant pour le compte d'autres (UGAP, CAIH, RESAH)"). Un nom
# seulement, jamais un SIRET codé en dur au hasard : la ligne réelle (siret,
# nom) est retrouvée en base et citée dans le résultat, pas supposée.
NOMS_CENTRALES_ACHAT = ["UGAP", "RESAH", "CAIH", "UNIHA"]


def detecter_centrale_achat(siret_acheteur: str, connexion) -> dict | None:
    """Sujet section 8 : un marché notifié par une centrale d'achat est
    rattaché en base au SIRET de la centrale, jamais à l'organisme
    bénéficiaire réel — élargir la recherche ne le retrouvera jamais."""
    ligne = connexion.execute(text(
        "SELECT siret, nom FROM acheteurs WHERE siret = :siret"
    ), {"siret": siret_acheteur}).fetchone()
    if ligne is None:
        return None
    siret, nom = ligne
    nom_upper = (nom or "").upper()
    for centrale in NOMS_CENTRALES_ACHAT:
        if centrale in nom_upper:
            return {"siret": siret, "nom": nom, "centrale_detectee": centrale}
    return None


def construire_message_centrale_achat(centrale: dict) -> str:
    """Message partagé entre agent_expansion_couverture() (appelé uniquement
    en cas de couverture faible) et fiche_de_faits.py (vérification
    inconditionnelle, cf. docstring du module : la limite tient à l'identité
    de l'acheteur, pas au volume de marchés retrouvés sous son SIRET)."""
    return (
        f"Marché notifié par une centrale d'achat ({centrale['nom']}, "
        f"détectée via le nom '{centrale['centrale_detectee']}'). L'organisme "
        "bénéficiaire réel n'est pas identifiable dans les données disponibles : "
        "DECP/TED rattachent le marché au SIRET de la centrale, jamais à "
        "l'établissement final."
    )


def _acheteur_a_un_historique(siret_acheteur: str, connexion) -> bool:
    return connexion.execute(text(
        "SELECT 1 FROM marches WHERE siret_acheteur = :siret LIMIT 1"
    ), {"siret": siret_acheteur}).fetchone() is not None


def _naf_acheteur(siret_acheteur: str, connexion) -> tuple[str, str | None] | None:
    """Code NAF et département (2 premiers chiffres du code postal) de
    l'acheteur, via le référentiel SIRENE national — jamais fabriqués si
    l'acheteur n'y est pas résolu."""
    ligne = connexion.execute(text("""
        SELECT su."activitePrincipaleUniteLegale", LEFT(se."codePostalEtablissement", 2)
        FROM acheteurs a
        JOIN sirene_stock_etablissement se ON se.siret = a.siret
        JOIN sirene_stock_unite_legale su ON su.siren = se.siren
        WHERE a.siret = :siret
    """), {"siret": siret_acheteur}).fetchone()
    if ligne is None or ligne[0] is None:
        return None
    return ligne[0], ligne[1]


def _acheteurs_meme_naf(
    siret_acheteur: str, naf: str, departement: str | None, connexion, limite: int = 20
) -> list[str]:
    """Autres acheteurs du même secteur (NAF), optionnellement restreints au
    même département. departement=None = périmètre national (axe
    "géographique élargi" du sujet)."""
    condition_zone = 'AND se."codePostalEtablissement" LIKE :prefixe' if departement else ""
    parametres = {"naf": naf, "siret": siret_acheteur, "limite": limite}
    if departement:
        parametres["prefixe"] = f"{departement}%"
    lignes = connexion.execute(text(f"""
        SELECT DISTINCT a.siret
        FROM acheteurs a
        JOIN sirene_stock_etablissement se ON se.siret = a.siret
        JOIN sirene_stock_unite_legale su ON su.siren = se.siren
        WHERE su."activitePrincipaleUniteLegale" = :naf
          {condition_zone}
          AND a.siret != :siret
        LIMIT :limite
    """), parametres).fetchall()
    return [row[0] for row in lignes]


def agent_expansion_couverture(siret_acheteur: str, code_cpv: str) -> dict:
    """
    Point d'entrée. Retourne un dict avec un champ "type" :
        - "centrale_achat" : limite de couverture signalée, expansion inutile.
        - "donnees_insuffisantes" : toutes les expansions tentées, aucune
          n'a suffi (ou l'acheteur n'a structurellement aucun historique).
        - "resultat" : un résultat exploitable (éventuellement obtenu après
          élargissement), avec la trace des axes tentés.
    """
    engine = get_engine()

    with engine.connect() as connexion:
        centrale = detecter_centrale_achat(siret_acheteur, connexion)
        if centrale is not None:
            return {
                "type": "centrale_achat",
                "acheteur": centrale,
                "message": construire_message_centrale_achat(centrale),
            }

        if not _acheteur_a_un_historique(siret_acheteur, connexion):
            return {
                "type": "donnees_insuffisantes",
                "message": "Aucun marché trouvé pour cet acheteur, sur aucun CPV — acheteur sans historique.",
                "expansions_tentees": [],
            }

        naf_departement = _naf_acheteur(siret_acheteur, connexion)

    resultat = detecter_sortant(siret_acheteur, code_cpv)
    expansions: list[dict] = []

    # Axe 1 : CPV parent — seul axe qui peut changer le sortant retourné.
    # .get(..., 0) partout ici : detecter_sortant() ne porte PAS la clé
    # "nb_marches_famille" dans son retour minimal (aucun marché trouvé pour
    # l'acheteur/CPV exact demandé — le cas normal quand un acheteur connu
    # n'a simplement jamais utilisé ce CPV précis) ; un accès direct par
    # crochets y plantait (KeyError, trouvé par revue de code indépendante
    # le 20/08/2026, reproduit sur un acheteur réel interrogé avec un CPV
    # hors de son historique).
    if resultat.get("nb_marches_famille", 0) < SEUIL_COUVERTURE_SUFFISANTE:
        for longueur in CPV_LONGUEURS_PARENT:
            if longueur >= len(code_cpv):
                continue
            prefixe = code_cpv[:longueur]
            candidat = detecter_sortant(siret_acheteur, prefixe, cpv_en_prefixe=True)
            expansions.append({
                "axe": "cpv_parent",
                "valeur": prefixe,
                "effet": f"{candidat.get('nb_marches_famille', 0)} marché(s) trouvé(s)",
            })
            if candidat.get("nb_marches_famille", 0) > resultat.get("nb_marches_famille", 0):
                resultat = candidat
            if resultat.get("nb_marches_famille", 0) >= SEUIL_COUVERTURE_SUFFISANTE:
                break

    # Axes 2/3 : acheteurs comparables, département puis national — n'élargissent
    # que les statistiques de prix/concurrents, jamais le sortant lui-même.
    acheteurs_comparables: list[str] = []
    if naf_departement is not None:
        naf, departement = naf_departement
        with engine.connect() as connexion:
            if departement:
                acheteurs_comparables = _acheteurs_meme_naf(siret_acheteur, naf, departement, connexion)
                if acheteurs_comparables:
                    expansions.append({
                        "axe": "acheteurs_comparables_departement",
                        "valeur": f"{len(acheteurs_comparables)} acheteur(s), NAF {naf}, département {departement}",
                        "effet": "statistiques de prix/concurrents élargies (jamais le sortant)",
                    })
            if not acheteurs_comparables:
                acheteurs_comparables = _acheteurs_meme_naf(siret_acheteur, naf, None, connexion)
                if acheteurs_comparables:
                    expansions.append({
                        "axe": "perimetre_geographique_national",
                        "valeur": f"{len(acheteurs_comparables)} acheteur(s), NAF {naf}, France entière",
                        "effet": "statistiques de prix/concurrents élargies (jamais le sortant)",
                    })

    # Axe 4 : fenêtre temporelle — structurellement un no-op ici (cf. docstring
    # du module) ; constaté et déclaré, pas simulé.
    expansions.append({
        "axe": "fenetre_temporelle",
        "valeur": "non applicable",
        "effet": (
            "detecter_sortant() n'applique déjà aucun filtre de date sur l'historique "
            "disponible ; la limite réelle est en amont, à l'ingestion (fenêtre fixe de "
            "3 ans, cf. README) — élargir cet axe ici ne changerait rien."
        ),
    })

    if resultat["sortant_probable"] is None and not acheteurs_comparables:
        return {
            "type": "donnees_insuffisantes",
            "message": (
                "Aucune expansion (CPV parent, acheteurs comparables, périmètre national) "
                "n'a permis de trouver une donnée exploitable pour cet acheteur/CPV."
            ),
            "expansions_tentees": expansions,
        }

    return {
        "type": "resultat",
        "resultat_sortant": resultat,
        "acheteurs_comparables": acheteurs_comparables,
        "expansions_appliquees": expansions,
    }


if __name__ == "__main__":
    import json

    # Exemple centrale d'achat : UGAP, réelle en base (77605646700587).
    print("--- Centrale d'achat (UGAP) ---")
    print(json.dumps(
        agent_expansion_couverture("77605646700587", "72000000"),
        indent=2, ensure_ascii=False, default=str,
    ))

    # Exemple acheteur sans historique.
    print("\n--- Acheteur sans historique ---")
    print(json.dumps(
        agent_expansion_couverture("00000000000000", "99999999"),
        indent=2, ensure_ascii=False, default=str,
    ))
