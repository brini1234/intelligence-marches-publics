def verbaliser(fiche: dict) -> str:
    """
    Transforme une fiche de faits en texte, selon un gabarit strict.
    Ne fait AUCUNE supposition : si un fait est absent, le dit explicitement.
    """
    if not fiche["faits"]:
        return f"Données insuffisantes : {fiche.get('raison', 'aucune information disponible')}."

    valeurs = {f["cle"]: f["valeur"] for f in fiche["faits"]}
    couverture = fiche["couverture_globale"]

    concurrents = valeurs["concurrents_observes"]
    concurrents_txt = ", ".join(concurrents) if isinstance(concurrents, list) else concurrents

    # Formulation conforme au sujet (section 2) : jamais "Prix du marché : X EUR"
    # (faux, ponctuel), toujours une fourchette avec taille d'échantillon et la
    # mention "indicatif" — un prix constaté sur d'autres marchés n'est jamais
    # une prédiction du prix futur.
    n = valeurs["nombre_marches_historique"]
    fourchette_txt = (
        f"{valeurs['fourchette_prix_min']:.0f} € à {valeurs['fourchette_prix_max']:.0f} € "
        f"(n={n}, indicatif)"
    )

    texte = (
        f"Titulaire actuel probable : {valeurs['titulaire_actuel']} "
        f"(dernier marché notifié le {valeurs['date_dernier_marche']}, "
        f"échéance estimée : {valeurs['date_expiration_estimee']}). "
        f"Concurrents observés : {concurrents_txt}. "
        f"Fourchette de prix constatée : {fourchette_txt}. "
        f"Pondération de l'acheteur : {valeurs['ponderation_acheteur']}. "
        f"Basé sur {n} marché(s) similaire(s) "
        f"(couverture globale : {couverture:.0%})."
    )
    return texte


if __name__ == "__main__":
    import sys
    sys.path.append(".")
    from scripts.fiche_de_faits import construire_fiche_de_faits

    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    print(verbaliser(fiche))