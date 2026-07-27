import sys
sys.path.append(".")

from scripts.detecter_sortant import detecter_sortant
from scripts.fiche_de_faits import construire_fiche_de_faits
from scripts.verbaliser import verbaliser
from scripts.verification_mecanique import verifier_texte

# Exemple riche connu, utilisé pour les vérifications qui ont besoin de vraies données
ACHETEUR_TEST = "11000028800016"  # Cour des Comptes
CPV_TEST = "72220000"             # Conseil en systèmes informatiques

resultats = []


def enregistrer(nom: str, succes: bool, detail: str = ""):
    resultats.append({"nom": nom, "succes": succes, "detail": detail})


def test_acheteur_sans_historique():
    """Piège du sujet : acheteur sans historique -> données insuffisantes."""
    resultat = detecter_sortant("00000000000000", "99999999")
    ok = resultat["confiance"] == "aucune" and resultat["sortant_probable"] is None
    enregistrer("Acheteur sans historique -> données insuffisantes", ok)


def test_cas_riche_produit_un_texte_valide():
    """Cas réel connu -> la fiche produit un texte qui passe la vérification mécanique."""
    fiche = construire_fiche_de_faits(ACHETEUR_TEST, CPV_TEST)
    texte = verbaliser(fiche)
    verification = verifier_texte(texte, fiche)
    enregistrer(
        "Cas riche (Cour des Comptes) -> texte valide",
        verification["valide"],
        texte if not verification["valide"] else "",
    )


def test_anti_hallucination_bloque_un_chiffre_invente():
    """Un chiffre absent de la fiche doit être détecté et rejeté."""
    fiche = construire_fiche_de_faits(ACHETEUR_TEST, CPV_TEST)
    texte_invente = "Le marché a été attribué pour un montant de 999999999 euros."
    verification = verifier_texte(texte_invente, fiche)
    ok = verification["valide"] is False and "999999999" in verification["nombres_non_justifies"]
    enregistrer("Anti-hallucination -> chiffre inventé rejeté", ok)


def test_bloc_de_decision_contient_les_5_elements():
    """Le sujet exige : sortant, concurrents, fourchette de prix, pondération, couverture globale."""
    fiche = construire_fiche_de_faits(ACHETEUR_TEST, CPV_TEST)
    cles = [f["cle"] for f in fiche["faits"]]
    elements_requis = [
        "titulaire_actuel",
        "concurrents_observes",
        "fourchette_prix_min",
        "fourchette_prix_max",
        "ponderation_acheteur",
    ]
    manquants = [e for e in elements_requis if e not in cles]
    ok = len(manquants) == 0 and "couverture_globale" in fiche
    enregistrer("Bloc de décision -> 5 éléments présents", ok, str(manquants) if manquants else "")


def test_couverture_est_honnete():
    """La couverture globale ne doit jamais afficher 100% si un fait est réellement absent."""
    fiche = construire_fiche_de_faits(ACHETEUR_TEST, CPV_TEST)
    ponderation = next(f for f in fiche["faits"] if f["cle"] == "ponderation_acheteur")
    ok = ponderation["couverture"] == 0.0 and fiche["couverture_globale"] < 1.0
    enregistrer("Couverture honnête (pas de 100% trompeur)", ok)


def test_bloc_de_decision_respecte_le_format():
    """Le sujet exige : 10 lignes maximum, avec les 5 éléments requis."""
    from scripts.bloc_de_decision import construire_bloc_de_decision
    lignes = construire_bloc_de_decision(ACHETEUR_TEST, CPV_TEST, "COUR DES COMPTES")
    ok = len(lignes) <= 10
    enregistrer("Bloc de décision -> 10 lignes maximum respectées", ok, f"{len(lignes)} lignes")



def cas_non_implementes():
    """
    Pièges du sujet (section 8) qui dépendent des 3 agents, pas encore construits.
    Listés explicitement pour ne jamais masquer ce qui manque.
    """
    return [
        "Marché passé par une centrale d'achat -> limite de couverture signalée",
        "CPV mal saisi -> complété par similarité (rapprochement vectoriel)",
        "Changement de raison sociale -> résolution correcte ou doute signalé",
        "Concurrent hors France -> score de confiance dégradé et déclaré",
    ]


def executer():
    print("=" * 70)
    print("HARNAIS D'ÉVALUATION — Intelligence concurrentielle marchés publics")
    print("=" * 70)

    test_acheteur_sans_historique()
    test_cas_riche_produit_un_texte_valide()
    test_anti_hallucination_bloque_un_chiffre_invente()
    test_bloc_de_decision_contient_les_5_elements()
    test_couverture_est_honnete()
    test_bloc_de_decision_respecte_le_format()

    print("\n--- Cas testés et automatisés ---")
    nb_echecs = 0
    for r in resultats:
        statut = "✅ PASS" if r["succes"] else "❌ FAIL"
        print(f"{statut} — {r['nom']}")
        if not r["succes"] and r["detail"]:
            print(f"         détail : {r['detail']}")
        if not r["succes"]:
            nb_echecs += 1

    print("\n--- Cas prévus par le sujet, non encore implémentés (agents) ---")
    for cas in cas_non_implementes():
        print(f"⚠️  NON IMPLÉMENTÉ — {cas}")

    print("\n" + "=" * 70)
    print(f"Résultat : {len(resultats) - nb_echecs}/{len(resultats)} vérifications automatisées réussies")
    print(f"{len(cas_non_implementes())} cas restent à couvrir par les futurs agents")
    print("=" * 70)

    return nb_echecs == 0


if __name__ == "__main__":
    succes = executer()
    sys.exit(0 if succes else 1)