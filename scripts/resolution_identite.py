"""
Hiérarchie de résolution d'identité (sujet, section 5) : SIRET exact
(niveau 1, déjà géré en amont — cf. transformer_silver_marches.py) ->
normalisation (niveau 2) -> rapprochement flou (niveau 3) -> agent
d'investigation d'identité (niveau 4, implémenté : continuité de marché
ci-dessous, historique SIRENE dans scripts/agent_investigation_identite.py).

Ce module n'est appelé QUE pour les identifiants qui échouent au niveau 1
(pas un SIRET à 14 chiffres exact). Découvert en explorant les données
réelles (bronze_ted_notices) : ces cas ne sont pas aléatoires, ils suivent
des formats identifiables :
    - SIRET avec espaces internes ("444 495 774 00531")
    - plusieurs SIRET concaténés dans un seul champ (co-traitance cachée)
    - SIREN seul, sans établissement (9 chiffres)
    - TVA intracommunautaire française (FR + 2 chiffres + SIREN)
    - TVA étrangère (2 lettres ISO hors FR + chiffres) -> piège "concurrent
      hors France" du sujet (section 8) : à déclarer, jamais à deviner
    - identifiants internes TED sans structure exploitable, ou codes courts
      non-SIRET -> seul le rapprochement flou sur le nom peut aboutir

Chaque résultat porte sa méthode ; les résultats de niveau 3 (flou) portent
en plus leur score de confiance et ne sont jamais traités comme aussi
certains qu'un résultat de niveau 1/2 (sujet section 8 : "changement de
raison sociale -> résolution correcte OU DOUTE SIGNALÉ").
"""
import re
import unicodedata

from sqlalchemy import text

REGEX_SIRET = re.compile(r"^\d{14}$")
REGEX_SIREN = re.compile(r"^\d{9}$")
REGEX_TVA_FR = re.compile(r"^FR\d{2}(\d{9})$")
REGEX_TVA_ETRANGERE = re.compile(r"^([A-Z]{2})[0-9A-Z]+$")
REGEX_PREFIXE_LABEL = re.compile(r"^(SIRET|SIREN)\s*:?\s*", re.IGNORECASE)

FORMES_JURIDIQUES = {
    "SA", "SAS", "SASU", "SARL", "EURL", "SCI", "GIE", "SCOP", "SNC",
    "EIRL", "EI", "SCM", "SELARL", "SC", "SCP",
}


def normaliser_nom(nom: str) -> str:
    """Majuscules, accents retirés, formes juridiques et ponctuation
    retirées, espaces multiples réduits. Utilisé pour le rapprochement
    flou comme pour toute comparaison de dénomination."""
    if not nom:
        return ""
    texte = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode("ascii")
    texte = texte.upper()
    texte = re.sub(r"[^\w\s]", " ", texte)
    mots = [m for m in texte.split() if m not in FORMES_JURIDIQUES]
    return " ".join(mots)


def _segments(identifiant: str) -> list[str]:
    identifiant = REGEX_PREFIXE_LABEL.sub("", identifiant.strip())
    return [s.strip() for s in re.split(r"[,;]", identifiant) if s.strip()]


def resoudre_par_normalisation(identifiant_brut: str | None) -> list[dict]:
    """
    Niveau 2 : règles déterministes, sans accès base. Retourne une liste
    (généralement 0 ou 1 élément, mais plusieurs pour un champ multi-valeurs
    — ex. co-traitance concaténée dans une seule chaîne). Chaque élément :
    {"siret": ... ou None, "siren": ... ou None, "methode": ..., "pays_etranger": ... ou None}.
    """
    if not identifiant_brut or not identifiant_brut.strip():
        return []

    resultats = []
    for segment in _segments(identifiant_brut):
        sans_espaces = re.sub(r"\s+", "", segment)

        if REGEX_SIRET.match(sans_espaces):
            methode = "espaces" if sans_espaces != segment else "siret_exact_segmente"
            resultats.append({"siret": sans_espaces, "siren": sans_espaces[:9], "methode": methode, "pays_etranger": None})
            continue

        tva_fr = REGEX_TVA_FR.match(sans_espaces)
        if tva_fr:
            resultats.append({"siret": None, "siren": tva_fr.group(1), "methode": "tva_fr", "pays_etranger": None})
            continue

        if REGEX_SIREN.match(sans_espaces):
            resultats.append({"siret": None, "siren": sans_espaces, "methode": "siren_seul", "pays_etranger": None})
            continue

        tva_etrangere = REGEX_TVA_ETRANGERE.match(sans_espaces)
        if tva_etrangere and tva_etrangere.group(1) != "FR":
            # Pas de SIRET français par nature (entité hors France) : un
            # pseudo-identifiant dérivé de la valeur brute nettoyée sert de
            # clé (même principe que la donnée déjà en base avant cette
            # évolution, pour rattacher la ligne à une entreprise
            # consultable plutôt que de perdre l'information). Toujours
            # marqué methode='etranger', jamais confondu avec un SIRET réel.
            pseudo = (sans_espaces + "0" * 14)[:14]
            resultats.append({"siret": pseudo, "siren": None, "methode": "etranger", "pays_etranger": tva_etrangere.group(1)})
            continue

    return resultats


def resoudre_siren_vers_siret_siege(siren: str, connexion) -> str | None:
    """Complète un SIREN seul (niveau 2 : tva_fr / siren_seul) en SIRET du
    siège via le référentiel SIRENE national. Aucun repli sur un
    établissement non-siège arbitraire : mieux vaut ne pas résoudre que
    de pointer vers un établissement potentiellement fermé ou non pertinent."""
    ligne = connexion.execute(text("""
        SELECT siret FROM sirene_stock_etablissement
        WHERE siren = :siren AND "etablissementSiege" = 'true'
        LIMIT 1
    """), {"siren": siren}).fetchone()
    return ligne[0] if ligne else None


def resoudre_par_similarite(nom_brut: str, connexion, seuil: float = 0.55) -> dict | None:
    """
    Niveau 3 : rapprochement flou (pg_trgm) contre le référentiel SIRENE
    national. N'est appelé que si le niveau 2 a échoué et qu'un nom est
    disponible. Retourne le meilleur candidat au-dessus du seuil, avec son
    score — jamais un résultat sans score, pour que l'appelant puisse
    toujours distinguer un résultat flou d'un résultat certain.

    En cas d'égalité au score maximum (ex. homonymie exacte : plusieurs
    SIREN partagent la même dénomination, cas réels mesurés : SMILE=113,
    BELHARRA=42) : Postgres ne garantit aucun ordre entre ex-aequo, donc
    choisir le premier reviendrait à un pick arbitraire présenté avec la
    même confiance qu'une correspondance unique. Retourne à la place un
    résultat marqué "ambigu" avec la liste **complète** des candidats à
    égalité, jamais un SIRET — c'est au niveau 4 (resoudre(), ci-dessous)
    de tenter une désambiguïsation avec du contexte supplémentaire.

    Une seule requête, l'égalité au score maximum calculée entièrement
    côté SQL (CTE + sous-requête MAX), jamais en repassant un score par
    Python — correctif du 18/08/2026, deuxième itération : une première
    version limitait la détection à 10 candidats (`LIMIT 10`), masquant la
    plupart des ex-aequo sur un nom très homonyme (vérifié : "SMILE" a 113
    candidats à score=1.0, dont seuls 10 étaient vus) ; la version
    intermédiaire qui a suivi (deux requêtes, la seconde comparant le score
    Python à `similarity()` recalculé en SQL) plantait par endroits
    (`IndexError`), la comparaison d'égalité entre un `real` PostgreSQL
    aller-retourné en `float` Python puis rebindé n'étant pas fiable bit à
    bit. En calculant `MAX(score)` et l'égalité dans la même requête, le
    score ne quitte jamais PostgreSQL avant la comparaison : plus de risque
    d'arrondi.
    """
    nom_normalise = normaliser_nom(nom_brut)
    if not nom_normalise:
        return None

    # Seuil pg_trgm relevé au niveau du seuil d'acceptation : le filtre
    # WHERE ... % ... s'appuie alors sur l'index GIN pour ne remonter que
    # les candidats déjà au-dessus du seuil, au lieu de classer par score
    # tous les candidats à faible similarité trouvés sur 29,8M lignes
    # (la différence est de l'ordre de la seconde contre plusieurs dizaines).
    connexion.execute(text("SET pg_trgm.similarity_threshold = :seuil"), {"seuil": seuil})
    lignes = connexion.execute(text("""
        WITH scores AS (
            SELECT siren, similarity(upper("denominationUniteLegale"), :nom) AS score
            FROM sirene_stock_unite_legale
            WHERE "denominationUniteLegale" % :nom
        )
        SELECT siren, score FROM scores WHERE score = (SELECT MAX(score) FROM scores)
    """), {"nom": nom_normalise}).fetchall()

    if not lignes:
        return None

    score_max = lignes[0][1]
    candidats_ex_aequo = [ligne[0] for ligne in lignes]

    if len(candidats_ex_aequo) > 1:
        return {
            "siret": None, "siren": None, "methode": "flou",
            "score_confiance": float(score_max),
            "ambigu": True, "candidats_ambigus": candidats_ex_aequo,
        }

    siren = candidats_ex_aequo[0]
    siret = resoudre_siren_vers_siret_siege(siren, connexion)
    return {"siret": siret, "siren": siren, "methode": "flou", "score_confiance": float(score_max)}


def resoudre_par_continuite_acheteur(candidats_sirens: list[str], siret_acheteur: str, connexion) -> dict | None:
    """
    Niveau 4a (investigation d'identité, sujet section 4) : parmi des
    candidats à égalité au niveau 3 (homonymie), un acheteur qui a déjà
    attribué un marché à l'un d'eux devient le signal de désambiguïsation —
    la continuité d'une relation acheteur/titulaire déjà observée dans les
    données, jamais une supposition. Recherché dans silver_attributions (même
    couche que l'appelant, transformer_silver_marches.py, y compris les
    résolutions déjà faites plus tôt dans la même exécution).

    Score dégradé (jamais 1.0, contrairement à un SIRET exact) : c'est un
    jugement contextuel qui peut se tromper (l'acheteur pourrait avoir
    traité avec deux entreprises homonymes différentes), pas une certitude —
    sujet section 8 : "changement de raison sociale -> résolution correcte
    OU DOUTE SIGNALÉ".
    """
    if not candidats_sirens:
        return None
    lignes = connexion.execute(text("""
        SELECT DISTINCT sa.siret_titulaire
        FROM silver_attributions sa
        JOIN silver_marches sm ON sm.uid = sa.uid
        WHERE sm.siret_acheteur = :siret_acheteur
          AND LEFT(sa.siret_titulaire, 9) = ANY(:sirens)
    """), {"siret_acheteur": siret_acheteur, "sirens": candidats_sirens}).fetchall()

    sirets_trouves = {ligne[0] for ligne in lignes}
    if len(sirets_trouves) != 1:
        return None  # aucune continuité, ou continuité elle-même ambiguë -> doute signalé

    siret = sirets_trouves.pop()
    return {
        "siret": siret, "siren": siret[:9],
        "methode": "investigation_continuite", "score_confiance": 0.75,
    }


def resoudre(
    identifiant_brut: str | None,
    nom_brut: str | None,
    connexion,
    siret_acheteur: str | None = None,
    avec_historique_sirene: bool = False,
) -> list[dict]:
    """
    Point d'entrée : applique le niveau 2, puis le niveau 3, puis (sujet
    section 4, "investigation d'identité") le niveau 4 quand le niveau 3
    est ambigu ou échoue totalement. Retourne une liste de résultats
    exploitables (siret non NULL, résultats etranger inclus pour être
    comptabilisés/déclarés) — jamais un identifiant inventé, une liste vide
    signifie une résolution qui échoue honnêtement.

    siret_acheteur : contexte optionnel (disponible pendant
    transformer_silver_marches.py) qui active le niveau 4a (continuité de
    marché, purement SQL, ci-dessus) en cas d'ambiguïté au niveau 3.

    avec_historique_sirene : active le niveau 4b (recherche dans l'historique
    des dénominations via l'API SIRENE, scripts/agent_investigation_identite.py)
    quand le niveau 3 échoue totalement. Désactivé par défaut : cette
    recherche est réseau-dépendante et rate-limited, elle ne doit jamais
    tourner automatiquement dans la boucle bronze->silver (qui doit rester
    rapide et sans dépendance réseau) — seuls scripts/mesurer_precision_resolution.py
    et scripts/agent_investigation_identite.py l'activent explicitement.
    """
    resultats_niveau_2 = resoudre_par_normalisation(identifiant_brut)

    resultats_finaux = []
    for r in resultats_niveau_2:
        if r["methode"] == "etranger":
            resultats_finaux.append(r)
            continue
        if r["siret"] is None and r["siren"] is not None:
            r["siret"] = resoudre_siren_vers_siret_siege(r["siren"], connexion)
        if r["siret"] is not None:
            resultats_finaux.append(r)

    if resultats_finaux:
        return resultats_finaux

    resultat_flou = resoudre_par_similarite(nom_brut, connexion) if nom_brut else None

    if resultat_flou and not resultat_flou.get("ambigu") and resultat_flou["siret"] is not None:
        # Niveau 3 confiant et non ambigu : c'est déjà le résultat le plus
        # fiable disponible. Ne PAS tenter le niveau 4 par-dessus — même un
        # résultat "surprenant" (ex. un homonyme actuel sans rapport avec
        # une célèbre entreprise renommée) reste, sans autre contexte, le
        # candidat le plus défendable : une correspondance réelle et
        # actuelle, pas une supposition.
        return [resultat_flou]

    # Ici : niveau 3 ambigu (candidats à égalité), totalement vide, ou un
    # candidat unique dont le SIREN n'a aucun établissement siège en base
    # (resoudre_siren_vers_siret_siege renvoie None sans que ce soit un cas
    # "ambigu" — vérifié : 21 696 SIREN sur 29,8M du stock national sont
    # dans ce cas). Dans les trois cas, aucun SIRET exploitable n'est
    # encore disponible ; niveau 4a (continuité, gratuit) d'abord si un
    # contexte acheteur existe.
    if resultat_flou and resultat_flou.get("ambigu") and siret_acheteur:
        resultat_continuite = resoudre_par_continuite_acheteur(
            resultat_flou["candidats_ambigus"], siret_acheteur, connexion
        )
        if resultat_continuite:
            return [resultat_continuite]

    # Niveau 4b (historique SIRENE, réseau, opt-in) en dernier recours.
    if avec_historique_sirene and nom_brut:
        # Import différé : évite un import circulaire au niveau module
        # (agent_investigation_identite.py importe normaliser_nom d'ici).
        from scripts.agent_investigation_identite import investiguer_via_historique_sirene
        resultat_historique = investiguer_via_historique_sirene(nom_brut, connexion)
        if resultat_historique and resultat_historique["siret"] is not None:
            return [resultat_historique]

    return []  # échec honnête : ambigu ou introuvable, jamais un pick arbitraire
