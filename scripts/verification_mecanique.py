import re


def extraire_nombres(texte: str) -> list[str]:
    """Extrait tous les nombres du texte, en ignorant les virgules de milliers."""
    texte_sans_virgules_milliers = re.sub(r"(\d),(\d{3})", r"\1\2", texte)
    return re.findall(r"\d+(?:\.\d+)?", texte_sans_virgules_milliers)


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
    Vérifie mécaniquement que chaque nombre du texte généré figure bien
    dans la fiche de faits ou dans les paramètres d'entrée légitimes.
    """
    nombres_dans_texte = extraire_nombres(texte)
    valeurs_autorisees = extraire_valeurs_autorisees(fiche, valeurs_connues_en_amont)

    nombres_non_justifies = [
        n for n in nombres_dans_texte if n not in valeurs_autorisees
    ]

    return {
        "valide": len(nombres_non_justifies) == 0,
        "nombres_non_justifies": nombres_non_justifies,
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