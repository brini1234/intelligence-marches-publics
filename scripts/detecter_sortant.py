import sys
sys.path.append(".")

import calendar
from datetime import date

from sqlalchemy import text
from db.connection import get_engine

# Tolérance (sujet, section 4 : "reconstituer les chaînes de renouvellement") :
# écart, en mois, jugé normal entre la fin ESTIMÉE d'une vague de marchés et
# le début de la suivante (renouvellement anticipé ou tardif fait partie de
# la pratique courante des marchés publics). Au-delà, ce n'est probablement
# pas un renouvellement mais des achats distincts partageant par coïncidence
# le même acheteur et le même CPV (ex. CPV générique).
SEUIL_COHERENCE_MOIS = 6

# Fenêtre (jours) sous laquelle plusieurs marchés du même acheteur/CPV sont
# considérés comme une seule "vague" de notification (plusieurs lots
# attribués en même temps, ex. accord-cadre découpé en lots séparés) plutôt
# que des étapes successives d'une chaîne de renouvellement. Découvert en
# explorant des données réelles (Cour des Comptes, CPV 72220000) : 3-4 lots
# à durées différentes notifiés à quelques jours d'intervalle chaque année —
# les comparer deux à deux comme une séquence produisait une fausse
# incohérence, alors qu'il s'agit d'un seul geste d'achat annuel.
FENETRE_GENERATION_JOURS = 30


def _ajouter_mois(d: date, mois: float) -> date:
    """
    Ajoute `mois` (arrondi à l'entier le plus proche : l'arithmétique
    calendaire n'a pas de sens au jour près sur une durée ESTIMÉE) à une
    date. N'est jamais utilisé pour une donnée source certaine, uniquement
    pour calculer une échéance estimée à partir d'une durée réelle ou
    inférée.
    """
    mois_entiers = round(mois)
    mois_total = d.month - 1 + mois_entiers
    annee = d.year + mois_total // 12
    mois_resultat = mois_total % 12 + 1
    jour = min(d.day, calendar.monthrange(annee, mois_resultat)[1])
    return date(annee, mois_resultat, jour)


def _mois_entre(d1: date, d2: date) -> float:
    """Nombre de mois (signé, approximatif) entre deux dates : d2 - d1."""
    return (d2.year - d1.year) * 12 + (d2.month - d1.month) + (d2.day - d1.day) / 30.44


def _duree_mediane_cpv(code_cpv: str, connexion) -> float | None:
    """
    Durée médiane (mois) observée sur ce CPV, tous acheteurs confondus —
    sert uniquement à inférer la durée d'un marché qui ne la publie pas
    (sujet section 4 : "durée ... inférée par famille de marché quand elle
    manque", ex. tous les marchés TED, cf. limite documentée dans le
    README). Jamais confondue avec une durée réellement publiée par la
    source : le résultat porte toujours son `duree_source` ("reelle" vs
    "inferee_famille_cpv") pour que les parties suivantes distinguent les
    deux plutôt que de les traiter comme aussi certaines l'une que l'autre.
    """
    valeur = connexion.execute(text("""
        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duree_mois)
        FROM marches
        WHERE code_cpv = :code_cpv AND duree_mois IS NOT NULL
    """), {"code_cpv": code_cpv}).scalar()
    return float(valeur) if valeur is not None else None


def _regrouper_en_generations(chaine: list[dict]) -> list[dict]:
    """
    Regroupe les entrées de chaîne (triées par date_notification croissante)
    en "vagues" de notification : plusieurs marchés notifiés à moins de
    FENETRE_GENERATION_JOURS d'intervalle sont un seul geste d'achat
    (plusieurs lots), pas des étapes successives d'un renouvellement. Chaque
    génération porte sa date de début (première notification du groupe) et
    sa date de fin estimée (la plus tardive parmi ses marchés — le
    renouvellement suivant ne peut logiquement survenir avant la fin du
    dernier lot encore actif).
    """
    if not chaine:
        return []

    generations = [[chaine[0]]]
    for entree in chaine[1:]:
        dernier_groupe = generations[-1]
        ecart_jours = (entree["date_notification"] - dernier_groupe[-1]["date_notification"]).days
        if ecart_jours <= FENETRE_GENERATION_JOURS:
            dernier_groupe.append(entree)
        else:
            generations.append([entree])

    resultat = []
    for groupe in generations:
        fins_connues = [g["date_fin_estimee"] for g in groupe if g["date_fin_estimee"] is not None]
        resultat.append({
            "marches": groupe,
            "date_debut": groupe[0]["date_notification"],
            "date_fin_estimee": max(fins_connues) if fins_connues else None,
        })
    return resultat


def detecter_sortant(siret_acheteur: str, code_cpv: str, cpv_en_prefixe: bool = False) -> dict:
    """
    Pour un acheteur et un code CPV donnés, identifie le titulaire probable actuel (le "sortant")
    et reconstitue la chaîne de renouvellement (sujet, section 4) :

    cpv_en_prefixe=True : `code_cpv` est traité comme un préfixe (LIKE) plutôt
    qu'une égalité exacte — utilisé uniquement par
    scripts/agent_expansion_couverture.py (axe "CPV parent" de l'agent
    d'expansion) pour élargir la famille de marchés sans dupliquer cette
    fonction.

    - "famille" de marchés = même acheteur, même code CPV (le rapprochement
      par objet sémantiquement proche malgré un CPV différent est un
      mécanisme séparé, cf. scripts/marches_similaires.py, S4 — piège "CPV
      mal saisi" du sujet section 8).
    - chaque marché de la famille reçoit une date de fin ESTIMÉE
      (date_notification + durée réelle si publiée, sinon durée médiane du
      CPV) : jamais un chiffre inventé, une durée non inférable laisse la
      date de fin à None plutôt que d'en fabriquer une.
    - une transition entre deux marchés consécutifs est jugée "cohérente"
      si l'écart entre la fin estimée du premier et le début du second
      reste dans la tolérance SEUIL_COHERENCE_MOIS. Le sortant probable
      reste le marché le plus récent, mais le niveau de confiance reflète
      désormais la cohérence de la chaîne, pas seulement le nombre de
      marchés observés — un acheteur avec des centaines de marchés sur un
      CPV générique et temporellement incohérents n'est jamais déclaré
      "confiance élevée" simplement parce que le volume est grand.
    - chaque concurrent de l'historique porte son etat_administratif
      (notamment 'ETRANGER'), pour que fiche_de_faits.py puisse dégrader la
      couverture et le déclarer explicitement — piège "concurrent hors
      France" du sujet (section 8).
    """
    engine = get_engine()
    condition_cpv = "m.code_cpv LIKE :code_cpv" if cpv_en_prefixe else "m.code_cpv = :code_cpv"
    parametre_cpv = f"{code_cpv}%" if cpv_en_prefixe else code_cpv

    with engine.connect() as connexion:
        resultats = connexion.execute(text(f"""
            SELECT m.uid, m.objet, m.montant, m.date_notification, m.duree_mois, m.duree_restante_mois,
                   a.siren_titulaire, e.denomination, e.etat_administratif
            FROM marches m
            JOIN attributions a ON a.uid_marche = m.uid
            JOIN entreprises e ON e.siren = a.siren_titulaire
            WHERE m.siret_acheteur = :siret_acheteur AND {condition_cpv}
            ORDER BY m.date_notification DESC
        """), {
            "siret_acheteur": siret_acheteur,
            "code_cpv": parametre_cpv,
        }).mappings().all()

        if not resultats:
            return {
                "sortant_probable": None,
                "confiance": "aucune",
                "raison": "Aucun marché trouvé pour cet acheteur et ce CPV",
                "marches_support": [],
                "historique": [],
                "chaine": [],
            }

        # Un marché (uid) peut avoir plusieurs titulaires (accord-cadre) :
        # la chaîne temporelle se construit au niveau MARCHÉ, pas au niveau
        # ligne d'attribution, sinon un accord-cadre à 9 titulaires
        # compterait pour 9 marchés dans la famille (le détail
        # multi-titulaires reste disponible dans `historique` ci-dessous).
        marches_par_uid = {}
        for r in resultats:
            marches_par_uid.setdefault(r["uid"], r)

        duree_mediane_cpv = None  # calculée paresseusement, au plus une fois
        duree_mediane_calculee = False
        chaine = []
        for r in sorted(marches_par_uid.values(), key=lambda ligne: ligne["date_notification"]):
            duree = r["duree_mois"]
            duree_source = "reelle"
            if duree is None:
                if not duree_mediane_calculee:
                    duree_mediane_cpv = _duree_mediane_cpv(code_cpv, connexion)
                    duree_mediane_calculee = True
                duree = duree_mediane_cpv
                duree_source = "inferee_famille_cpv" if duree is not None else "inconnue"
            date_fin_estimee = _ajouter_mois(r["date_notification"], float(duree)) if duree else None
            chaine.append({
                "uid": r["uid"],
                "date_notification": r["date_notification"],
                "duree_mois": float(duree) if duree is not None else None,
                "duree_source": duree_source,
                "date_fin_estimee": date_fin_estimee,
            })

        generations = _regrouper_en_generations(chaine)
        nb_generations = len(generations)

        transitions_coherentes = 0
        transitions_total = 0
        for precedent, suivant in zip(generations, generations[1:]):
            if precedent["date_fin_estimee"] is None:
                continue
            transitions_total += 1
            ecart = _mois_entre(precedent["date_fin_estimee"], suivant["date_debut"])
            if abs(ecart) <= SEUIL_COHERENCE_MOIS:
                transitions_coherentes += 1

        ratio_coherence = (transitions_coherentes / transitions_total) if transitions_total else None

        marche_actuel = resultats[0]
        nb_marches_famille = len(marches_par_uid)

        if nb_generations == 1:
            confiance = "faible"
        elif ratio_coherence is None:
            confiance = "faible"
        elif nb_generations >= 3 and ratio_coherence >= 0.7:
            confiance = "élevée"
        elif ratio_coherence >= 0.5:
            confiance = "moyenne"
        else:
            confiance = "faible"

        derniere_entree = chaine[-1]

        raison = (
            f"{nb_marches_famille} marché(s) sur {nb_generations} vague(s) de notification "
            f"observée(s) pour cet acheteur sur ce CPV"
        )
        if ratio_coherence is not None:
            raison += f", chaîne de renouvellement cohérente à {ratio_coherence:.0%}"

        return {
            "sortant_probable": marche_actuel["denomination"],
            "siren_sortant": marche_actuel["siren_titulaire"],
            "date_notification": str(marche_actuel["date_notification"]),
            "duree_restante_mois": marche_actuel["duree_restante_mois"],
            "date_expiration_estimee": str(derniere_entree["date_fin_estimee"]) if derniere_entree["date_fin_estimee"] else None,
            "duree_source": derniere_entree["duree_source"],
            "confiance": confiance,
            "nb_marches_famille": nb_marches_famille,
            "nb_vagues_notification": nb_generations,
            "chaine_coherente": ratio_coherence is not None and ratio_coherence >= 0.5,
            "ratio_coherence_chaine": round(ratio_coherence, 2) if ratio_coherence is not None else None,
            "raison": raison,
            "marches_support": list(marches_par_uid.keys()),
            "historique": [
                {
                    "uid": r["uid"],
                    "denomination": r["denomination"],
                    "montant": float(r["montant"]) if r["montant"] else None,
                    "etat_administratif": r["etat_administratif"],
                }
                for r in resultats
            ],
            "chaine": [
                {
                    **c,
                    "date_notification": str(c["date_notification"]),
                    "date_fin_estimee": str(c["date_fin_estimee"]) if c["date_fin_estimee"] else None,
                }
                for c in chaine
            ],
        }


if __name__ == "__main__":
    import json
    # Exemple : Cour des Comptes, CPV 72220000 (conseil en systèmes informatiques)
    resultat = detecter_sortant("11000028800016", "72220000")
    print(json.dumps(resultat, indent=2, ensure_ascii=False, default=str))
