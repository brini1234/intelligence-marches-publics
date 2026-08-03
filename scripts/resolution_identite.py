"""
Hiérarchie de résolution d'identité (sujet, section 5) : SIRET exact
(niveau 1, déjà géré en amont — cf. transformer_silver_marches.py) ->
normalisation (niveau 2) -> rapprochement flou (niveau 3) -> agent
(niveau 4, hors périmètre ici, comme les deux autres agents déjà différés).

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
    ligne = connexion.execute(text("""
        SELECT siren, similarity(upper("denominationUniteLegale"), :nom) AS score
        FROM sirene_stock_unite_legale
        WHERE "denominationUniteLegale" % :nom
        ORDER BY score DESC
        LIMIT 1
    """), {"nom": nom_normalise}).fetchone()

    if ligne is None or ligne[1] < seuil:
        return None

    siren, score = ligne
    siret = resoudre_siren_vers_siret_siege(siren, connexion)
    return {"siret": siret, "siren": siren, "methode": "flou", "score_confiance": float(score)}


def resoudre(identifiant_brut: str | None, nom_brut: str | None, connexion) -> list[dict]:
    """
    Point d'entrée : applique le niveau 2 puis, en dernier recours, le
    niveau 3. Retourne une liste de résultats exploitables (siret non NULL,
    résultats etranger inclus pour être comptabilisés/déclarés) — jamais un
    identifiant inventé, une liste vide signifie une résolution qui échoue
    honnêtement.
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
    if resultat_flou and resultat_flou["siret"] is not None:
        return [resultat_flou]

    return []
