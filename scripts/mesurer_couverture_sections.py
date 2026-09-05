"""
Affiche la couverture par section (fait) d'une fiche de faits, pour un ou
plusieurs cas de référence -- "La couverture est un citoyen de première
classe : chaque section du briefing affiche son taux de complétude" (sujet,
section 4).

Usage :
    python scripts/mesurer_couverture_sections.py
"""
import sys
sys.path.append(".")

from scripts.fiche_de_faits import construire_fiche_de_faits

CAS = [
    ("11000028800016", "72220000", "Cour des Comptes (riche)"),
    ("77605646700587", "72220000", "UGAP (centrale d'achat)"),
    ("00000000000000", "72220000", "Acheteur inconnu (sans historique)"),
]

for siret, cpv, label in CAS:
    fiche = construire_fiche_de_faits(siret, cpv)
    print("=" * 72)
    print(f"{label}  (SIRET={siret}, CPV={cpv})")
    print("=" * 72)
    if fiche.get("type") == "donnees_insuffisantes":
        print(f"  couverture_globale = {fiche['couverture_globale']:.2f}  (données insuffisantes)")
        continue
    for fait in fiche["faits"]:
        print(f"  {fait['cle']:<28} couverture={fait['couverture']:.2f}   valeur={str(fait['valeur'])[:60]}")
    print(f"  {'--- GLOBALE ---':<28} couverture={fiche['couverture_globale']:.2f}")
    print()
