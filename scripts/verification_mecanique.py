import re


def extraire_nombres(texte: str) -> list[str]:
    """Extrait tous les nombres du texte (entiers ou décimaux)."""
    return re.findall(r"\d+(?:[.,]\d+)?", texte)


def extraire_valeurs_autorisees(fiche: dict) -> set[str]:
    """
    Construit l'ensemble de toutes les valeurs numériques et textuelles
    qui ont le droit d'apparaître dans le texte, car elles viennent de la fiche.
    """
    autorisees = set()
    for fait in fiche.get("faits", []):
        valeur = str(fait["valeur"])
        autorisees.add(valeur)
        # On ajoute aussi chaque nombre trouvé dans la valeur (utile pour les dates, ex: "2026-07-21")
        autorisees.update(extraire_nombres(valeur))
    # Le pourcentage de couverture est aussi une valeur légitime à apparaître
    couverture_pct = str(round(fiche.get("couverture_globale", 0) * 100))
    autorisees.add(couverture_pct)
    return autorisees


def verifier_texte(texte: str, fiche: dict) -> dict:
    """
    Vérifie mécaniquement que chaque nombre du texte généré figure bien
    dans la fiche de faits. Si un nombre n'est pas reconnu, le texte est rejeté.
    """
    nombres_dans_texte = extraire_nombres(texte)
    valeurs_autorisees = extraire_valeurs_autorisees(fiche)

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