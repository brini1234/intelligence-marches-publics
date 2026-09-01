"""
Sorties structurées (sujet, section 9, Environnement technique : "Sorties
structurées : Pydantic et JSON Schéma, validation systématique"). Deux
objets structurés du produit sont validés ici :

    - FicheDeFaits : la fiche de faits elle-même (sujet, section 4,
      Mécanisme anti-hallucination : "un objet JSON où chaque fait porte sa
      provenance et son score de couverture" — seule entrée du modèle de
      langage, cf. verbaliser.py). scripts/fiche_de_faits.py construit son
      retour puis le fait passer par ce modèle avant de le renvoyer : une
      valeur de type inattendu, une couverture hors [0,1] ou une provenance
      vide lèvent une erreur de validation immédiate au lieu de se propager
      silencieusement jusqu'au texte final.
    - BlocDeDecision : le bloc de décision final (sujet, section 2 :
      "bloc de décision de 10 lignes maximum"). La contrainte de longueur
      devient ici une validation structurelle (max_length=10), pas
      seulement une convention respectée par construction du code
      appelant — un futur ajout de ligne qui dépasserait la limite est
      détecté à la validation, pas seulement en relisant le texte.

JSON Schema exporté dans schema/ (python scripts/schemas.py régénère les
deux fichiers) : artefact indépendant du code Python, consultable/utilisable
par un outil tiers, conforme à l'exigence du sujet ("Pydantic ET JSON
Schéma", pas l'un ou l'autre).
"""
import sys
sys.path.append(".")

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class Fait(BaseModel):
    """Un fait unique de la fiche de faits — sujet section 4 : "chaque fait
    porte sa provenance et son score de couverture"."""

    cle: str = Field(min_length=1)
    # Les faits produits par scripts/fiche_de_faits.py portent soit une
    # valeur scalaire (nom d'entreprise, date en texte, montant, nombre de
    # marchés), soit la liste des concurrents observés, soit None (aucune
    # durée disponible) — jamais un type structuré arbitraire.
    valeur: str | int | float | Decimal | list[str] | None
    provenance: str = Field(min_length=1)
    couverture: float = Field(ge=0.0, le=1.0)


class FicheDeFaits(BaseModel):
    """
    Sortie de scripts/fiche_de_faits.py::construire_fiche_de_faits().
    Deux formes possibles, toutes deux valides ici :
        - faits=[], raison=<texte> : données insuffisantes ou centrale
          d'achat détectée (aucun fait exploitable) ;
        - faits=[Fait, ...], marches_support=[uid, ...] : cas normal.
    """

    faits: list[Fait]
    couverture_globale: float = Field(ge=0.0, le=1.0)
    raison: str | None = None
    marches_support: list[str] | None = None


class BlocDeDecision(BaseModel):
    """Sujet, section 2 : "la sortie principale est un bloc de décision de
    10 lignes maximum"."""

    lignes: list[str] = Field(min_length=1, max_length=10)

    @field_validator("lignes")
    @classmethod
    def _lignes_non_vides(cls, valeur: list[str]) -> list[str]:
        if any(not ligne.strip() for ligne in valeur):
            raise ValueError("une ligne du bloc de décision ne peut pas être vide")
        return valeur


if __name__ == "__main__":
    # Régénère schema/fiche_de_faits.schema.json et schema/bloc_de_decision.schema.json
    # Usage : python scripts/schemas.py
    import json
    import os

    os.makedirs("schema", exist_ok=True)
    for nom, modele in [("fiche_de_faits", FicheDeFaits), ("bloc_de_decision", BlocDeDecision)]:
        chemin = f"schema/{nom}.schema.json"
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(modele.model_json_schema(), f, indent=2, ensure_ascii=False)
        print(f"{chemin} généré")
