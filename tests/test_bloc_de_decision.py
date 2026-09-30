import sys
sys.path.append(".")
from scripts.bloc_de_decision import construire_bloc_de_decision


def test_bloc_de_decision_respecte_la_limite_de_10_lignes():
    lignes = construire_bloc_de_decision("11000028800016", "72220000", "COUR DES COMPTES")
    assert len(lignes) <= 10


def test_bloc_de_decision_gere_absence_de_donnees():
    lignes = construire_bloc_de_decision("00000000000000", "99999999", "ACHETEUR INCONNU")
    assert len(lignes) <= 10
    assert any("INSUFFISANTES" in ligne for ligne in lignes)


def test_bloc_de_decision_gere_famille_sans_aucun_montant_publie():
    # Cas réel (marché TED sans montant) : ne doit jamais planter en
    # formatant None comme un nombre (`{prix_min:,.0f}` sur None). Depuis
    # l'agent d'expansion (S6), ce cas peut désormais être élargi et
    # retrouver un montant sur un périmètre plus large — la ligne
    # "Fourchette de prix" doit alors être correctement formatée (pas
    # planter), pas nécessairement rester "non disponible". La ligne
    # "Pondération de l'acheteur" contient toujours "non disponible"
    # (aucune source connectée ne la fournit) : on vise explicitement la
    # ligne fourchette de prix pour ne pas se reposer dessus par erreur.
    lignes = construire_bloc_de_decision("13000208200043", "72267000", "TEST")
    assert len(lignes) <= 10
    ligne_prix = next(l for l in lignes if l.startswith("Fourchette de prix"))
    assert "non disponible" in ligne_prix or "€" in ligne_prix

def test_bloc_de_decision_affiche_confiance_sources_et_montants_au_format_francais():
    # Sujet, section 4 : "un sortant probable avec un niveau de confiance et
    # les identifiants des marchés qui l'étayent" ; lecteur français : jamais
    # "41,864 €" (lu comme 41 virgule 864).
    import re
    from scripts.fiche_de_faits import construire_fiche_de_faits
    from scripts.verification_mecanique import verifier_texte

    lignes = construire_bloc_de_decision("11000028800016", "72220000", "COUR DES COMPTES")
    ligne_sortant = next(l for l in lignes if l.startswith("Sortant probable"))
    assert re.search(r"confiance (élevée|moyenne|faible)", ligne_sortant)
    assert any("marché du sortant :" in l for l in lignes)
    ligne_prix = next(l for l in lignes if l.startswith("Fourchette de prix"))
    assert not re.search(r"\d,\d{3}", ligne_prix)

    # Le bloc lui-même ne cite que des valeurs de la fiche, de l'entrée ou
    # ses propres libellés fixes.
    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    libelles_du_bloc = ["Objet", "CPV", "COUVERTURE GLOBALE"]
    resultat = verifier_texte(
        "\n".join(lignes), fiche,
        valeurs_connues_en_amont=["11000028800016", "72220000", "COUR DES COMPTES"]
        + libelles_du_bloc + fiche["marches_support"],
    )
    assert resultat["valide"] is True, resultat
