"""
Recoupement et détection BOAMP (sujet, section 3 : "BOAMP | France, avis |
Moyenne | Recoupement et détection"). Rôle documenté par le sujet, jamais
dévié ici : BOAMP n'a pas de SIRET (cf. connectors/boamp.py, vérifié en
conditions réelles), donc jamais utilisé comme source d'identité ni
d'ingestion gold — uniquement pour recouper les avis d'attribution CPV72
France du cache local (scripts/charger_cache_boamp.py) contre ce que la
base gold (DECP + TED) contient déjà, et détecter les écarts.

Rapprochement volontairement approximatif (nom d'acheteur normalisé + CPV à
4 chiffres + fenêtre de date) — pas une jointure exacte, cohérent avec la
fiabilité "Moyenne" du sujet pour cette source (à la différence de DECP qui
publie un SIRET, section 3 : "transforme une supposition en jointure
exacte"). Ce script ne modifie jamais la base : lecture seule, un rapport
imprimé, jamais une insertion de donnée BOAMP dans les tables métier.

Usage (après scripts/charger_cache_boamp.py) :
    python scripts/detecter_recoupement_boamp.py
"""
import json
import sys
from datetime import date, datetime

sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine
from scripts.charger_cache_boamp import CHEMIN_CACHE
from scripts.resolution_identite import normaliser_nom

# Fenêtre de tolérance entre la date de parution BOAMP (annonce) et la date
# de notification DECP/TED (attribution effective) : ce ne sont pas la même
# date par nature (l'avis est publié avant/pendant la notification), donc
# une fenêtre plus large que le rapprochement DECP/TED inter-sources (30
# jours, transformer_silver_marches.py) est nécessaire ici — documentée
# comme un choix explicite, pas une exactitude prétendue.
FENETRE_JOURS = 90


def _charger_cache() -> list[dict]:
    try:
        with open(CHEMIN_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _charger_marches_gold(connexion) -> dict[tuple[str, str], list[date]]:
    """Index (acheteur normalisé, CPV à 4 chiffres) -> liste de dates de
    notification, pour tout le périmètre gold CPV72 France."""
    lignes = connexion.execute(text("""
        SELECT a.nom, m.code_cpv, m.date_notification
        FROM marches m
        JOIN acheteurs a ON a.siret = m.siret_acheteur
        WHERE m.date_notification IS NOT NULL
    """)).fetchall()

    index: dict[tuple[str, str], list[date]] = {}
    for nom, code_cpv, date_notif in lignes:
        cle = (normaliser_nom(nom), (code_cpv or "")[:4])
        index.setdefault(cle, []).append(date_notif)
    return index


def _correspond(avis_boamp: dict, index: dict) -> bool:
    nom_normalise = normaliser_nom(avis_boamp.get("nomacheteur") or "")
    date_parution = avis_boamp.get("date_parution")
    if not nom_normalise or not date_parution:
        return False
    try:
        date_parution = datetime.strptime(date_parution[:10], "%Y-%m-%d").date()
    except ValueError:
        return False

    for code_cpv in avis_boamp.get("codes_cpv", []):
        dates_gold = index.get((nom_normalise, code_cpv[:4]))
        if not dates_gold:
            continue
        if any(abs((d - date_parution).days) <= FENETRE_JOURS for d in dates_gold):
            return True
    return False


def detecter_recoupement_boamp():
    avis_boamp = _charger_cache()
    if not avis_boamp:
        print(f"Aucun avis en cache ({CHEMIN_CACHE}) — lancer d'abord : python scripts/charger_cache_boamp.py")
        return

    engine = get_engine()
    with engine.connect() as connexion:
        index_gold = _charger_marches_gold(connexion)

    correspondants = []
    non_correspondants = []
    for avis in avis_boamp:
        if _correspond(avis, index_gold):
            correspondants.append(avis)
        else:
            non_correspondants.append(avis)

    print("=" * 72)
    print("RECOUPEMENT BOAMP — sujet section 3 (\"Recoupement et détection\")")
    print("=" * 72)
    print(f"Avis BOAMP CPV72xxxxxx France (cache) : {len(avis_boamp)}")
    print(f"  Recoupés avec un marché déjà présent en gold (DECP/TED)     : "
          f"{len(correspondants)} ({len(correspondants) / len(avis_boamp):.0%})")
    print(f"  SANS correspondance en gold — signal de détection          : "
          f"{len(non_correspondants)} ({len(non_correspondants) / len(avis_boamp):.0%})")
    print(f"  (rapprochement approximatif : acheteur normalisé + CPV4 + ±{FENETRE_JOURS}j — "
          f"jamais une jointure exacte, BOAMP ne publie pas de SIRET, cf. connectors/boamp.py)")

    if non_correspondants:
        print(f"\nExemples d'avis BOAMP sans correspondance gold détectée (10 premiers sur {len(non_correspondants)}) :")
        for avis in non_correspondants[:10]:
            print(f"  - {avis['date_parution']} | {avis['nomacheteur']} | "
                  f"CPV {avis['codes_cpv']} | {avis['objet'][:70] if avis['objet'] else ''}")
        print("  Un avis non recoupé n'est PAS une preuve d'erreur DECP/TED : peut aussi "
              "signifier une variante de dénomination d'acheteur non normalisée par ce "
              "rapprochement simple, ou un marché encore non publié côté DECP/TED au "
              "moment du chargement — signal à recouper manuellement, jamais inséré "
              "automatiquement en base (BOAMP n'a pas de SIRET, cf. connectors/boamp.py).")
    print("=" * 72)


if __name__ == "__main__":
    detecter_recoupement_boamp()
