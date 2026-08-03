"""
Vérification finale de la partie SIRENE avant de passer à l'étape suivante.

Rassemble en un seul rapport reproductible tous les contrôles faits
manuellement pendant l'implémentation : volumétrie, doublons, couverture,
cohérence référentielle entre entreprises/etablissements/stock national.

Usage :
    python scripts/verification_finale_sirene.py
"""
import sys
sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine

resultats = []


def _verifier(nom: str, ok: bool, detail: str = ""):
    resultats.append({"nom": nom, "ok": ok, "detail": detail})


def executer():
    engine = get_engine()

    with engine.begin() as connexion:
        # --- Volumétrie du référentiel national ---
        nb_ul = connexion.execute(text("SELECT COUNT(*) FROM sirene_stock_unite_legale")).scalar()
        nb_etab = connexion.execute(text("SELECT COUNT(*) FROM sirene_stock_etablissement")).scalar()
        _verifier(
            "Stock national chargé en totalité (> 25M unités légales, > 40M établissements)",
            nb_ul > 25_000_000 and nb_etab > 40_000_000,
            f"{nb_ul:,} unités légales, {nb_etab:,} établissements".replace(",", " "),
        )

        # --- Pas de doublons de clé dans le stock national ---
        nb_ul_distincts = connexion.execute(text("SELECT COUNT(DISTINCT siren) FROM sirene_stock_unite_legale")).scalar()
        nb_etab_distincts = connexion.execute(text("SELECT COUNT(DISTINCT siret) FROM sirene_stock_etablissement")).scalar()
        _verifier(
            "Aucun doublon de clé dans le stock national",
            nb_ul == nb_ul_distincts and nb_etab == nb_etab_distincts,
            f"unités légales: {nb_ul} lignes / {nb_ul_distincts} SIREN distincts ; "
            f"établissements: {nb_etab} lignes / {nb_etab_distincts} SIRET distincts",
        )

        # --- Couverture et catégorisation complète de `entreprises` ---
        nb_entreprises = connexion.execute(text("SELECT COUNT(*) FROM entreprises")).scalar()
        nb_categorisees = connexion.execute(text("""
            SELECT COUNT(*) FROM entreprises
            WHERE code_naf IS NOT NULL
               OR etat_administratif IN ('INTROUVABLE_API', 'ETRANGER', 'SIREN_MALFORME', 'NON_DIFFUSIBLE')
        """)).scalar()
        _verifier(
            "100% des entreprises ont un statut connu (enrichies OU explicitement catégorisées comme non résolues)",
            nb_categorisees == nb_entreprises,
            f"{nb_categorisees}/{nb_entreprises} catégorisées"
            + ("" if nb_categorisees == nb_entreprises else
               f" — {nb_entreprises - nb_categorisees} entreprise(s) ni enrichies ni marquées, à investiguer"),
        )

        # --- Aucune ligne avec denomination vide malgré la contrainte NOT NULL ---
        nb_denomination_vide = connexion.execute(text(
            "SELECT COUNT(*) FROM entreprises WHERE TRIM(denomination) = ''"
        )).scalar()
        _verifier("Aucune dénomination vide (chaîne '' au lieu de NULL/valeur)", nb_denomination_vide == 0,
                   f"{nb_denomination_vide} ligne(s) concernée(s)")

        # --- Cohérence référentielle etablissements -> entreprises ---
        nb_etablissements_orphelins = connexion.execute(text("""
            SELECT COUNT(*) FROM etablissements et
            WHERE NOT EXISTS (SELECT 1 FROM entreprises e WHERE e.siren = et.siren)
        """)).scalar()
        _verifier(
            "Aucun établissement orphelin (sans entreprise correspondante)",
            nb_etablissements_orphelins == 0,
            f"{nb_etablissements_orphelins} orphelin(s)"
            + (" — impossible normalement, la FK aurait dû bloquer l'insertion" if nb_etablissements_orphelins else ""),
        )

        # --- Couverture etablissements vs attributions ---
        nb_sirets_attributions = connexion.execute(text(
            "SELECT COUNT(DISTINCT siret_titulaire) FROM attributions WHERE siret_titulaire IS NOT NULL"
        )).scalar()
        nb_etablissements = connexion.execute(text("SELECT COUNT(*) FROM etablissements")).scalar()
        taux_couverture_etab = nb_etablissements / nb_sirets_attributions if nb_sirets_attributions else 0
        _verifier(
            "Couverture etablissements >= 95% des SIRET titulaires réels",
            taux_couverture_etab >= 0.95,
            f"{nb_etablissements}/{nb_sirets_attributions} ({taux_couverture_etab:.0%})",
        )

        # --- Cas hors France bien isolés, pas mélangés avec les vrais échecs ---
        nb_etrangers = connexion.execute(text(
            "SELECT COUNT(*) FROM entreprises WHERE etat_administratif = 'ETRANGER'"
        )).scalar()
        _verifier(
            "Titulaires hors France détectés et isolés (piège 'concurrent hors France')",
            nb_etrangers > 0,
            f"{nb_etrangers} entreprise(s) marquée(s) ETRANGER",
        )

        # --- Aucune valeur '' résiduelle dans les colonnes texte clés du stock national ---
        nb_vides_residuels = connexion.execute(text("""
            SELECT COUNT(*) FROM sirene_stock_unite_legale
            WHERE "denominationUniteLegale" = ''
        """)).scalar()
        _verifier(
            "Nettoyage '' -> NULL bien appliqué sur le stock national",
            nb_vides_residuels == 0,
            f"{nb_vides_residuels} chaîne(s) vide(s) résiduelle(s) trouvée(s)",
        )

    print("=" * 72)
    print("VÉRIFICATION FINALE — PARTIE SIRENE")
    print("=" * 72)
    nb_echecs = 0
    for r in resultats:
        statut = "✅ PASS" if r["ok"] else "❌ FAIL"
        print(f"{statut} — {r['nom']}")
        print(f"         {r['detail']}")
        if not r["ok"]:
            nb_echecs += 1
    print("=" * 72)
    print(f"Résultat : {len(resultats) - nb_echecs}/{len(resultats)} vérifications réussies")
    print("=" * 72)
    return nb_echecs == 0


if __name__ == "__main__":
    ok = executer()
    sys.exit(0 if ok else 1)
