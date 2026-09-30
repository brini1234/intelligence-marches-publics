import re

# Une dénomination sociale (SIRENE) apparaît toujours entièrement en
# majuscules dans ce projet, alors que le reste du gabarit de
# verbaliser.py/verbaliser_llm.py est en casse de phrase normale ("Titulaire
# actuel probable : ...", "Concurrents observés : ..."). Une suite de mots
# TOUT EN MAJUSCULES est donc, dans ce texte, soit un nom d'entreprise réel
# recopié depuis la fiche, soit un nom halluciné par le LLM — jamais un mot
# de gabarit (qui n'a que sa première lettre en majuscule).
REGEX_NOM_CANDIDAT = re.compile(
    r"\b[A-ZÀ-Ü][A-ZÀ-Ü0-9&\-']{1,}(?:\s+[A-ZÀ-Ü][A-ZÀ-Ü0-9&\-']{1,})*\b"
)

# Correctif du 30/09/2026 : REGEX_NOM_CANDIDAT ne voit que les noms TOUT EN
# MAJUSCULES — un LLM qui écrit un nom inventé en casse normale
# ("Capgemini", "Sopra Steria") passait la porte sans être détecté (vérifié
# sur la fiche réelle de la Cour des comptes). Tout mot à majuscule
# initiale doit donc soit appartenir au vocabulaire fixe du gabarit
# (verbaliser.py / verbaliser_llm.py), soit apparaître dans la fiche.
REGEX_MOT_CAPITALISE = re.compile(r"\b[A-ZÀ-Ý][a-zà-ÿ]+(?:[-'][A-Za-zÀ-ÿ]+)*")
REGEX_MOT = re.compile(r"[A-Za-zÀ-ÿ]+")
VOCABULAIRE_GABARIT = {
    m.lower() for m in REGEX_MOT.findall(
        "Titulaire actuel probable dernier marché notifié le échéance estimée "
        "Concurrents concurrent observés observé Aucun dans les données "
        "disponibles Fourchette de prix constatée non disponible indicatif "
        "aucun montant publié sur cette famille Pondération de l'acheteur "
        "Basé marchés similaires couverture globale Données insuffisantes "
        "Sortant Échéance Historique"
    )
}

# Correctif du 30/09/2026 : une date n'était contrôlée que composante par
# composante (2026, 12, 11) — une date inventée recombinée à partir de
# composantes présentes ailleurs dans la fiche passait la porte. Les dates
# sont désormais contrôlées comme un tout.
REGEX_DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
REGEX_DATE_FR = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")

# Séparateurs de milliers français (espace, espace insécable, espace fine
# insécable) : "41 864 €" est un montant, pas les deux nombres 41 et 864.
REGEX_MILLIERS_FR = re.compile(r"(\d)[   ](?=\d{3}(?!\d))")


def extraire_nombres(texte: str) -> list[str]:
    """Extrait tous les nombres du texte, en ignorant les séparateurs de milliers (virgule ou espace)."""
    texte_sans_separateurs = re.sub(r"(\d),(\d{3})", r"\1\2", texte)
    texte_sans_separateurs = REGEX_MILLIERS_FR.sub(r"\1", texte_sans_separateurs)
    return re.findall(r"\d+(?:\.\d+)?", texte_sans_separateurs)


def extraire_dates(texte: str) -> list[str]:
    """Extrait les dates du texte, normalisées au format ISO (AAAA-MM-JJ)."""
    dates = REGEX_DATE_ISO.findall(texte)
    dates += [f"{a}-{m}-{j}" for j, m, a in REGEX_DATE_FR.findall(texte)]
    return dates


def extraire_noms_candidats(texte: str) -> list[str]:
    """Extrait les suites de mots tout en majuscules du texte (cf. REGEX_NOM_CANDIDAT)."""
    return [m.strip(" .,;:") for m in REGEX_NOM_CANDIDAT.findall(texte)]


def extraire_mots_capitalises(texte: str) -> list[str]:
    """Extrait les mots à majuscule initiale en casse normale (cf. REGEX_MOT_CAPITALISE)."""
    return REGEX_MOT_CAPITALISE.findall(texte)


def extraire_valeurs_autorisees(fiche: dict, valeurs_connues_en_amont: list = None) -> set[str]:
    """
    Construit l'ensemble de toutes les valeurs numériques et textuelles
    qui ont le droit d'apparaître dans le texte, car elles viennent :
    - de la fiche de faits (valeurs + scores de couverture),
    - ou de paramètres d'entrée légitimes (ex: code CPV, SIRET), fournis
      explicitement par l'appelant, jamais devinés.
    """
    autorisees = set()

    for fait in fiche.get("faits", []):
        valeur = fait["valeur"]
        valeurs_a_traiter = valeur if isinstance(valeur, list) else [valeur]

        for v in valeurs_a_traiter:
            v_str = str(v)
            autorisees.add(v_str)
            autorisees.update(extraire_nombres(v_str))
            # Un concurrent observé est stocké avec sa fréquence attachée
            # (ex. "RSM FRANCE (1/11 attribution(s))") : le nom seul doit
            # rester autorisé si le LLM le cite sans ce suffixe.
            autorisees.update(extraire_noms_candidats(v_str))
            if isinstance(v, (int, float)):
                autorisees.add(str(int(v)))

        # Le score de couverture individuel de ce fait, exprimé en pourcentage (ex: 100, 0, 66)
        couverture_pct = str(round(fait.get("couverture", 0) * 100))
        autorisees.add(couverture_pct)

    couverture_globale_pct = str(round(fiche.get("couverture_globale", 0) * 100))
    autorisees.add(couverture_globale_pct)

    # Fiche sans faits ("Données insuffisantes : <raison>") : la raison fait
    # partie de la fiche et peut légitimement citer des noms et des nombres
    # (ex. "centrale d'achat ... (UGAP)") — sans cela, le texte de repli
    # déterministe échouait à sa propre vérification.
    raison = fiche.get("raison")
    if raison:
        autorisees.add(str(raison))
        autorisees.update(extraire_nombres(str(raison)))
        autorisees.update(extraire_noms_candidats(str(raison)))

    if valeurs_connues_en_amont:
        for v in valeurs_connues_en_amont:
            autorisees.add(str(v))
            autorisees.update(extraire_nombres(str(v)))

    return autorisees


def verifier_texte(texte: str, fiche: dict, valeurs_connues_en_amont: list = None) -> dict:
    """
    Vérifie mécaniquement que chaque nombre ET chaque nom d'entreprise du
    texte généré figurent bien dans la fiche de faits ou dans les
    paramètres d'entrée légitimes (sujet, section 4 : "tout nombre, tout
    nom d'entreprise et toute date du texte figurent bien dans la fiche de
    faits ; sinon, le texte est rejeté et régénéré").
    """
    nombres_dans_texte = extraire_nombres(texte)
    noms_dans_texte = extraire_noms_candidats(texte)
    valeurs_autorisees = extraire_valeurs_autorisees(fiche, valeurs_connues_en_amont)

    dates_autorisees = set()
    mots_autorises = set(VOCABULAIRE_GABARIT)
    for v in valeurs_autorisees:
        dates_autorisees.update(extraire_dates(v))
        mots_autorises.update(m.lower() for m in REGEX_MOT.findall(v))

    nombres_non_justifies = [
        n for n in nombres_dans_texte if n not in valeurs_autorisees
    ]
    noms_non_justifies = [
        n for n in noms_dans_texte if n not in valeurs_autorisees
    ]
    noms_non_justifies += [
        m for m in extraire_mots_capitalises(texte)
        if any(p.lower() not in mots_autorises for p in REGEX_MOT.findall(m))
    ]
    dates_non_justifiees = [
        d for d in extraire_dates(texte) if d not in dates_autorisees
    ]

    return {
        "valide": not (nombres_non_justifies or noms_non_justifies or dates_non_justifiees),
        "nombres_non_justifies": nombres_non_justifies,
        "noms_non_justifies": noms_non_justifies,
        "dates_non_justifiees": dates_non_justifiees,
    }


if __name__ == "__main__":
    import sys
    sys.path.append(".")
    from scripts.fiche_de_faits import construire_fiche_de_faits
    from scripts.verbaliser import verbaliser

    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    texte = verbaliser(fiche)
    resultat = verifier_texte(texte, fiche)

    print("Texte généré :", texte)
    print("Vérification :", resultat)