"""
Point d'entrée du produit (sujet, section 1 : "entrée simple (un acheteur,
un objet de marché), sortie sous forme de fiche JSON et de rapport
lisible" ; section 2 : "le rapport détaillé est un complément optionnel,
jamais l'objet principal" ; section 7 : "démonstration : acheteur et objet
de marché vers un bloc de décision sourcé").

Ajouté le 30/09/2026 : jusqu'ici, obtenir un briefing supposait de modifier
le SIRET/CPV codés en dur dans le `__main__` de bloc_de_decision.py, et
aucun rapport détaillé n'existait.

    - acheteur : SIRET (14 chiffres) ou nom (recherché dans `acheteurs` ;
      plusieurs candidats -> liste affichée, jamais un choix arbitraire) ;
    - objet : code CPV exact (--cpv) ou texte libre (--objet), auquel cas le
      CPV est déduit par similarité d'embeddings (scripts/marches_similaires.py
      — piège "CPV mal saisi", section 8), avec son score, jamais présenté
      comme certain ;
    - sortie : bloc de décision (toujours), fiche de faits JSON (--json),
      rapport détaillé Markdown (--rapport), verbalisation par LLM au lieu
      du gabarit déterministe (--llm, repli automatique sans clé).

Usage :
    python scripts/briefing.py --acheteur 11000028800016 --cpv 72220000
    python scripts/briefing.py --acheteur "cour des comptes" --objet "audit du système d'information" \\
        --json sortie/fiche.json --rapport sortie/rapport.md
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine
from scripts.bloc_de_decision import construire_bloc_de_decision
from scripts.fiche_de_faits import construire_fiche_de_faits
from scripts.verbaliser import verbaliser
from scripts.verification_mecanique import verifier_texte

NB_VOISINS_CPV = 20
# Mesuré le 30/09/2026 (similarité max contre les 27 271 marchés avec
# embedding) : objets informatiques réels 0.81-0.90, "construction d'un pont
# en béton" 0.68, "zzzz qqqq" 0.53 — mais "bonjour" 0.75 : le petit modèle
# local est mal calibré en absolu, ce seuil n'écarte que le hors-sujet
# franc. D'où un CPV déduit toujours affiché "indicatif", avec sa part de
# votes, et --cpv recommandé quand le code est connu.
SIMILARITE_MIN_CPV = 0.7
MAX_CANDIDATS_ACHETEUR = 5
MAX_MARCHES_RAPPORT = 30


class EntreeAmbigue(Exception):
    """L'entrée ne permet pas de choisir sans arbitraire : l'appelant doit préciser."""


def resoudre_acheteur(entree: str) -> tuple[str, str | None]:
    """SIRET ou nom -> (siret, nom). Nom ambigu -> EntreeAmbigue avec les candidats."""
    siret = re.sub(r"\s", "", entree)
    with get_engine().connect() as connexion:
        if re.fullmatch(r"\d{14}", siret):
            nom = connexion.execute(
                text("SELECT nom FROM acheteurs WHERE siret = :siret"), {"siret": siret}
            ).scalar()
            return siret, nom

        candidats = connexion.execute(text("""
            SELECT a.siret, a.nom, COUNT(m.uid) AS nb_marches
            FROM acheteurs a LEFT JOIN marches m ON m.siret_acheteur = a.siret
            WHERE a.nom ILIKE :motif
            GROUP BY a.siret, a.nom
            ORDER BY nb_marches DESC, a.siret
        """), {"motif": f"%{entree.strip()}%"}).mappings().all()

    exacts = [c for c in candidats if c["nom"].strip().upper() == entree.strip().upper()]
    if len(exacts) == 1:
        return exacts[0]["siret"], exacts[0]["nom"]
    if len(candidats) == 1:
        return candidats[0]["siret"], candidats[0]["nom"]
    if not candidats:
        raise EntreeAmbigue(f"Aucun acheteur connu ne correspond à « {entree} ». Préciser un SIRET.")
    liste = "\n".join(
        f"  {c['siret']}  {c['nom']} ({c['nb_marches']} marché(s))"
        for c in candidats[:MAX_CANDIDATS_ACHETEUR]
    )
    reste = len(candidats) - MAX_CANDIDATS_ACHETEUR
    raise EntreeAmbigue(
        f"{len(candidats)} acheteurs correspondent à « {entree} » — préciser le SIRET :\n{liste}"
        + (f"\n  ... et {reste} autre(s)" if reste > 0 else "")
    )


def deduire_cpv(objet: str) -> dict:
    """
    Texte libre -> CPV le plus représenté parmi les marchés les plus proches
    (vote pondéré par la similarité). Retourne aussi de quoi juger la
    fiabilité de la déduction, jamais un CPV présenté comme certain.
    """
    from scripts.marches_similaires import trouver_marches_similaires

    voisins = [v for v in trouver_marches_similaires(texte=objet, limite=NB_VOISINS_CPV) if v["code_cpv"]]
    if not voisins or voisins[0]["similarite"] < SIMILARITE_MIN_CPV:
        meilleure = f"{voisins[0]['similarite']:.2f}" if voisins else "aucune"
        raise EntreeAmbigue(
            f"Objet « {objet} » trop éloigné de tout marché connu (similarité max : {meilleure}, "
            f"seuil {SIMILARITE_MIN_CPV}). Préciser un code CPV avec --cpv."
        )

    poids = defaultdict(float)
    effectifs = defaultdict(int)
    for v in voisins:
        poids[v["code_cpv"]] += float(v["similarite"])
        effectifs[v["code_cpv"]] += 1
    cpv = max(poids, key=lambda c: (poids[c], c))
    return {
        "code_cpv": cpv,
        "voisins_concordants": effectifs[cpv],
        "voisins_total": len(voisins),
        "similarite_max": round(float(max(v["similarite"] for v in voisins if v["code_cpv"] == cpv)), 2),
    }


def _marches_sources(uids: list[str]) -> list[dict]:
    if not uids:
        return []
    with get_engine().connect() as connexion:
        return [dict(r) for r in connexion.execute(text("""
            SELECT m.uid, m.date_notification, m.montant, m.duree_mois, m.code_cpv, m.objet,
                   string_agg(DISTINCT e.denomination, ', ') AS titulaires
            FROM marches m
            LEFT JOIN attributions a ON a.uid_marche = m.uid
            LEFT JOIN entreprises e ON e.siren = a.siren_titulaire
            WHERE m.uid = ANY(:uids)
            GROUP BY m.uid
            ORDER BY m.date_notification DESC, m.uid
            LIMIT :limite
        """), {"uids": uids, "limite": MAX_MARCHES_RAPPORT}).mappings().all()]


def _cellule(valeur) -> str:
    if valeur is None:
        return "—"
    if isinstance(valeur, list):
        valeur = ", ".join(valeur) if valeur else "aucun"
    return str(valeur).replace("|", "\\|").replace("\n", " ")


def construire_rapport(entree: dict, lignes_bloc: list[str], fiche: dict, synthese: str, verification: dict) -> str:
    """Rapport détaillé Markdown : complément du bloc, chaque fait avec sa provenance et sa couverture."""
    r = [f"# Briefing concurrentiel — {entree['nom_acheteur'] or entree['siret_acheteur']}", ""]
    r += [f"- Acheteur : {entree['nom_acheteur'] or 'nom inconnu'} (SIRET {entree['siret_acheteur']})",
          f"- Code CPV : {entree['code_cpv']}"]
    if entree.get("cpv_deduit"):
        d = entree["cpv_deduit"]
        r.append(f"- CPV déduit de l'objet « {entree['objet']} » par similarité : "
                 f"{d['voisins_concordants']}/{d['voisins_total']} marchés voisins, similarité max "
                 f"{d['similarite_max']} — indicatif, à confirmer")
    r += ["", "## Bloc de décision", "", "```", *lignes_bloc, "```", "",
          "## Synthèse", "", synthese, "",
          f"Vérification mécanique (nombres, noms, dates présents dans la fiche) : "
          f"{'valide' if verification['valide'] else 'REJETÉE — ' + json.dumps(verification, ensure_ascii=False)}",
          ""]

    if fiche["faits"]:
        r += ["## Faits, provenance et couverture", "",
              "| Fait | Valeur | Couverture | Provenance |", "|---|---|---|---|"]
        for f in fiche["faits"]:
            r.append(f"| {f['cle']} | {_cellule(f['valeur'])} | {f['couverture']:.0%} | {_cellule(f['provenance'])} |")
        trous = [f["cle"] for f in fiche["faits"] if f["couverture"] < 1.0]
        r += ["", f"Couverture globale : {fiche['couverture_globale']:.0%}. "
              + (f"Faits incomplets (couverture < 100 %) : {', '.join(trous)}." if trous else "Aucun fait incomplet."), ""]

        support = fiche.get("marches_support") or []
        marches = _marches_sources(support)
        r += [f"## Marchés sources ({len(support)} au total"
              + (f", {MAX_MARCHES_RAPPORT} plus récents affichés" if len(support) > MAX_MARCHES_RAPPORT else "")
              + ")", "",
              "| uid | Notification | Montant (€) | Durée (mois) | CPV | Titulaire(s) | Objet |",
              "|---|---|---|---|---|---|---|"]
        for m in marches:
            montant = f"{m['montant']:,.0f}".replace(",", " ") if m["montant"] is not None else None
            duree = f"{m['duree_mois']:.0f}" if m["duree_mois"] is not None else None
            objet = (m["objet"] or "")[:120]
            r.append(f"| {m['uid']} | {m['date_notification']} | {_cellule(montant)} | {_cellule(duree)} | "
                     f"{m['code_cpv']} | {_cellule(m['titulaires'])} | {_cellule(objet)} |")
        r.append("")
    else:
        r += ["## Données insuffisantes", "", fiche.get("raison") or "Aucune information disponible.", ""]

    r += ["## Limites", "",
          "- Concurrents observés dans les données publiques (DECP, TED), jamais une liste exhaustive.",
          "- Fourchettes de prix indicatives : les montants DECP sont souvent le plafond d'un accord-cadre, "
          "pas la dépense réelle.",
          "- Pondération prix/technique : aucune source connectée ne la publie.", ""]
    return "\n".join(r)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Briefing concurrentiel : acheteur + objet de marché -> bloc de décision.")
    parser.add_argument("--acheteur", required=True, help="SIRET (14 chiffres) ou nom de l'acheteur")
    objet = parser.add_mutually_exclusive_group(required=True)
    objet.add_argument("--cpv", help="code CPV exact (ex. 72220000)")
    objet.add_argument("--objet", help="objet du marché en texte libre (CPV déduit par similarité)")
    parser.add_argument("--json", help="écrit la fiche de faits JSON à ce chemin")
    parser.add_argument("--rapport", help="écrit le rapport détaillé Markdown à ce chemin")
    parser.add_argument("--llm", action="store_true",
                        help="verbalise la synthèse par LLM (porte de vérification, repli déterministe sans clé)")
    args = parser.parse_args(argv)

    try:
        siret, nom = resoudre_acheteur(args.acheteur)
        cpv_deduit = deduire_cpv(args.objet) if args.objet else None
    except EntreeAmbigue as e:
        print(e, file=sys.stderr)
        return 2
    code_cpv = cpv_deduit["code_cpv"] if cpv_deduit else args.cpv

    if cpv_deduit:
        print(f"CPV déduit de l'objet par similarité : {code_cpv} "
              f"({cpv_deduit['voisins_concordants']}/{cpv_deduit['voisins_total']} marchés voisins, "
              f"similarité max {cpv_deduit['similarite_max']}) — indicatif")

    lignes = construire_bloc_de_decision(siret, code_cpv, nom)
    print("=" * 60)
    for i, ligne in enumerate(lignes, start=1):
        print(f"{i}. {ligne}")
    print("=" * 60)

    if args.json or args.rapport:
        fiche = construire_fiche_de_faits(siret, code_cpv)
        for chemin in (args.json, args.rapport):
            if chemin and os.path.dirname(chemin):
                os.makedirs(os.path.dirname(chemin), exist_ok=True)
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(fiche, f, indent=2, ensure_ascii=False, default=str)
            print(f"Fiche de faits : {args.json}")
        if args.rapport:
            if args.llm:
                from scripts.verbaliser_llm import verbaliser_via_llm
                synthese = verbaliser_via_llm(fiche)
            else:
                synthese = verbaliser(fiche)
            entree = {"siret_acheteur": siret, "nom_acheteur": nom, "code_cpv": code_cpv,
                      "objet": args.objet, "cpv_deduit": cpv_deduit}
            rapport = construire_rapport(entree, lignes, fiche, synthese, verifier_texte(synthese, fiche))
            with open(args.rapport, "w", encoding="utf-8") as f:
                f.write(rapport)
            print(f"Rapport détaillé : {args.rapport}")
    return 0


if __name__ == "__main__":
    # Console Windows (cp1252) : jamais un plantage d'affichage sur un
    # caractère hors page de code, cf. README (bug d'encodage déjà rencontré).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    sys.exit(main())
