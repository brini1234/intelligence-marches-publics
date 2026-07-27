def verbaliser(fiche: dict) -> str:
    """
    Transforme une fiche de faits en texte, selon un gabarit strict.
    Ne fait AUCUNE supposition : si un fait est absent, le dit explicitement.
    """
    if not fiche["faits"]:
        return f"Données insuffisantes : {fiche.get('raison', 'aucune information disponible')}."

    valeurs = {f["cle"]: f["valeur"] for f in fiche["faits"]}
    couverture = fiche["couverture_globale"]

    texte = (
        f"Titulaire actuel probable : {valeurs['titulaire_actuel']}. "
        f"Dernier marché notifié le {valeurs['date_dernier_marche']}, "
        f"avec environ {valeurs['duree_restante_mois']} mois restants avant échéance. "
        f"Cette estimation s'appuie sur {valeurs['nombre_marches_historique']} marché(s) "
        f"similaire(s) observé(s) pour cet acheteur (couverture : {couverture:.0%})."
    )
    return texte


if __name__ == "__main__":
    import sys
    sys.path.append(".")
    from scripts.fiche_de_faits import construire_fiche_de_faits

    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    print(verbaliser(fiche))