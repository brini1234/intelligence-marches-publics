import sys
sys.path.append(".")

from scripts.fiche_de_faits import construire_fiche_de_faits
from scripts.schemas import BlocDeDecision


def _valider(lignes: list[str]) -> list[str]:
    """
    Sortie structurée, validation systématique (sujet, section 9). Sujet,
    section 2 : "bloc de décision de 10 lignes maximum" — devient ici une
    contrainte structurelle (BlocDeDecision, max_length=10), pas seulement
    une convention respectée par construction du code appelant : un futur
    ajout de ligne qui dépasserait la limite lève une erreur de validation
    immédiate plutôt que de silencieusement produire un bloc trop long.
    """
    return BlocDeDecision(lignes=lignes).lignes


def construire_bloc_de_decision(siret_acheteur: str, code_cpv: str, nom_acheteur: str = None) -> list[str]:
    """
    Construit le bloc de décision : 10 lignes maximum, lisible en 30 secondes,
    avec la couverture affichée à chaque section concernée.
    """
    fiche = construire_fiche_de_faits(siret_acheteur, code_cpv)

    if not fiche["faits"]:
        return _valider([
            f"Acheteur : {nom_acheteur or siret_acheteur} | Objet CPV : {code_cpv}",
            f"DONNÉES INSUFFISANTES : {fiche.get('raison', 'aucune information disponible')}",
            "COUVERTURE GLOBALE : 0%",
        ])

    valeurs = {f["cle"]: f for f in fiche["faits"]}

    def pct(cle: str) -> str:
        return f"{valeurs[cle]['couverture']:.0%}"

    concurrents = valeurs["concurrents_observes"]["valeur"]
    concurrents_txt = ", ".join(concurrents) if isinstance(concurrents, list) else concurrents

    prix_min = valeurs["fourchette_prix_min"]["valeur"]
    prix_max = valeurs["fourchette_prix_max"]["valeur"]
    n = valeurs["nombre_marches_historique"]["valeur"]
    if prix_min is None or prix_max is None:
        fourchette_txt = f"non disponible (n={n}, aucun montant publié sur cette famille)"
    else:
        fourchette_txt = f"{prix_min:,.0f} € — {prix_max:,.0f} € (n={n}, indicatif)"

    lignes = [
        f"Acheteur : {nom_acheteur or siret_acheteur} | Objet CPV : {code_cpv}",
        f"Sortant probable : {valeurs['titulaire_actuel']['valeur']} (couverture: {pct('titulaire_actuel')})",
        f"Échéance estimée : {valeurs['date_expiration_estimee']['valeur']} "
        f"(dernier marché: {valeurs['date_dernier_marche']['valeur']}) "
        f"(couverture: {pct('date_expiration_estimee')})",
        f"Concurrents observés : {concurrents_txt} (couverture: {pct('concurrents_observes')})",
        f"Fourchette de prix : {fourchette_txt} "
        f"(couverture: {pct('fourchette_prix_min')})",
        f"Pondération de l'acheteur : {valeurs['ponderation_acheteur']['valeur']} "
        f"(couverture: {pct('ponderation_acheteur')})",
        f"Historique : {valeurs['nombre_marches_historique']['valeur']} marché(s) similaire(s) observé(s)",
        f"COUVERTURE GLOBALE : {fiche['couverture_globale']:.0%}",
    ]
    return _valider(lignes)


def afficher_bloc(lignes: list[str]) -> None:
    print("=" * 60)
    for i, ligne in enumerate(lignes, start=1):
        print(f"{i}. {ligne}")
    print("=" * 60)


if __name__ == "__main__":
    lignes = construire_bloc_de_decision("11000028800016", "72220000", "COUR DES COMPTES")
    afficher_bloc(lignes)
    