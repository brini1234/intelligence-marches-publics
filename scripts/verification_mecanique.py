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


def extraire_nombres(texte: str) -> list[str]:
    """Extrait tous les nombres du texte, en ignorant les virgules de milliers."""
    texte_sans_virgules_milliers = re.sub(r"(\d),(\d{3})", r"\1\2", texte)
    return re.findall(r"\d+(?:\.\d+)?", texte_sans_virgules_milliers)


def extraire_noms_candidats(texte: str) -> list[str]:
    """Extrait les suites de mots tout en majuscules du texte (cf. REGEX_NOM_CANDIDAT)."""
    return [m.strip(" .,;:") for m in REGEX_NOM_CANDIDAT.findall(texte)]


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

    nombres_non_justifies = [
        n for n in nombres_dans_texte if n not in valeurs_autorisees
    ]
    noms_non_justifies = [
        n for n in noms_dans_texte if n not in valeurs_autorisees
    ]

    return {
        "valide": len(nombres_non_justifies) == 0 and len(noms_non_justifies) == 0,
        "nombres_non_justifies": nombres_non_justifies,
        "noms_non_justifies": noms_non_justifies,
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