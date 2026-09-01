"""
Récupère et met en cache localement les avis BOAMP "Résultat de marché"
du périmètre du sujet (CPV 72xxxxxx, France, 3 ans) — cf.
connectors/boamp.py pour le détail de l'exploration de l'API (sujet,
section 6, S1 : "Explorer TED, DECP et BOAMP à la main").

BOAMP n'est PAS une source d'identité (aucun SIRET disponible, vérifié en
conditions réelles — cf. connectors/boamp.py) : son rôle, documenté par le
sujet (section 3), est "Recoupement et détection" — jamais une source
d'ingestion pour les tables gold (marches/attributions), qui exigent une
identité fiable. Ce script se contente donc de récupérer et de mettre en
cache le brut, sans jamais l'insérer dans le pipeline bronze/silver/gold ;
scripts/detecter_recoupement_boamp.py consomme ce cache pour produire un
rapport de recoupement en lecture seule, jamais une écriture en base.

Mise en cache locale (comme data/decp/decp.parquet) : le fetch complet
interroge ~136 000 avis nationaux tous secteurs (pagination 100/page, seul
maximum accepté par l'API) pour n'en retenir qu'une fraction CPV72 côté
client (cf. connectors/boamp.py, le CPV n'est pas un facet filtrable côté
serveur) — plusieurs minutes de réseau, à ne pas relancer à chaque
consultation du rapport de recoupement.

Usage :
    python scripts/charger_cache_boamp.py
"""
import json
import os
import sys
import time

sys.path.append(".")

from connectors.boamp import rechercher_resultats_marche

CHEMIN_CACHE = "data/boamp/resultats_cpv72_france_3ans.json"


def charger_cache_boamp():
    print("Récupération des avis BOAMP 'Résultat de marché' (CPV 72xxxxxx, France, 3 ans) ...")
    print("  Pagination complète sur ~136 000 avis nationaux tous secteurs (filtrage CPV côté client) — plusieurs minutes.")
    debut = time.time()
    resultats = rechercher_resultats_marche(prefixe_cpv="72", annees_historique=3)
    duree = time.time() - debut

    os.makedirs(os.path.dirname(CHEMIN_CACHE), exist_ok=True)
    with open(CHEMIN_CACHE, "w", encoding="utf-8") as f:
        json.dump(resultats, f, ensure_ascii=False)

    print(f"\n✅ {len(resultats)} avis CPV72xxxxxx mis en cache dans {CHEMIN_CACHE} ({duree:.0f}s)")


if __name__ == "__main__":
    charger_cache_boamp()
