"""
Verbalisation par LLM (sujet, section 4, "Mécanisme anti-hallucination" et
section 9, "Modèle de langage : passerelle interne, budget précisé au
démarrage") — pièce manquante identifiée le 01/09/2026 : jusqu'ici,
scripts/verbaliser.py était un gabarit texte 100% déterministe (f-strings),
sans aucun appel à un modèle de langage, alors que le sujet en décrit un
explicitement, protégé par un cycle génère→vérifie→régénère.

Ce module ajoute ce cycle sans jamais changer la garantie déjà en place :
    1. construit un prompt contenant UNIQUEMENT la fiche de faits (sujet :
       "sans outil ni accès à la base") ;
    2. appelle le LLM (passerelle : SDK Anthropic officiel, cf. skill
       claude-api) pour verbaliser selon le gabarit strict ;
    3. vérifie mécaniquement le texte produit (scripts/verification_mecanique.py) ;
    4. si invalide, régénère en signalant explicitement les valeurs
       rejetées, jusqu'à MAX_TENTATIVES fois ;
    5. si toujours invalide, ou en cas d'erreur réseau/authentification/
       tout autre échec de l'appel LLM : repli sur le gabarit déterministe
       de scripts/verbaliser.py — même philosophie de dégradation gracieuse
       que scripts/agent_enrichissement_web.py, jamais un texte invalide
       livré, jamais un crash.

Modèle : claude-haiku-4-5 (1 $/5 $ par million de tokens in/out, le moins
cher de la gamme Claude actuelle — cf. skill claude-api). Choix corrigé le
01/09/2026 : la première version de ce fichier utilisait claude-opus-5 par
défaut de la skill claude-api ("ALWAYS use claude-opus-5 unless the user
explicitly names a different model"), appliqué sans le confronter à la
tâche réelle — une erreur signalée par l'utilisateur, corrigée ici. La
tâche confiée au modèle est volontairement étroite et fermée : reformuler
une fiche de faits DÉJÀ validée selon un gabarit de phrase fixe, sans
raisonnement, sans recherche, sans décision — exactement le type de tâche
que le sujet (section 9) qualifie de "budget précisé au démarrage", pas
un cas justifiant le modèle le plus capable. Pas de paramètre `effort` ici
: Haiku 4.5 ne le supporte pas (erreur documentée dans la skill claude-api
pour les modèles antérieurs à la génération 4.6) — le seul levier de coût
disponible sur ce modèle est le choix du modèle lui-même, déjà fait.

Nuance assumée, pas mesurée : au moment d'écrire ce fichier, aucune
mesure comparative coût/latence Opus vs Haiku n'existe encore sur ce
chemin précis (scripts/mesurer_cout_latence_briefing.py sera étendu après
la fin du rebuild en cours pour logger le coût réel en tokens, cf.
rapport de stage section 6). Le choix de Haiku ici est donc justifié par
l'adéquation à la tâche (reformulation contrainte, pas de raisonnement
ouvert), pas encore par un chiffre coût/latence comparatif réel.
"""
import json
import os
import sys

sys.path.append(".")

from scripts.verbaliser import verbaliser
from scripts.verification_mecanique import verifier_texte

MODELE_LLM = "claude-haiku-4-5"
MAX_TENTATIVES = 3
MAX_TOKENS_REPONSE = 1024

GABARIT_STRICT = (
    "Titulaire actuel probable : [titulaire_actuel] (dernier marché notifié "
    "le [date_dernier_marche], échéance estimée : [date_expiration_estimee]). "
    "[Concurrents observés : <liste séparée par des virgules>. OU, si la "
    "liste est vide, exactement : Aucun concurrent observé dans les données "
    "disponibles.] Fourchette de prix constatée : [<montant min> € à "
    "<montant max> € (n=<n>, indicatif)] OU [non disponible (n=<n>, aucun "
    "montant publié sur cette famille)]. Pondération de l'acheteur : "
    "[ponderation_acheteur]. Basé sur <n> marché(s) similaire(s) "
    "(couverture globale : <couverture_globale en %>)."
)

SYSTEM_PROMPT = f"""Tu es un générateur de texte strictement contraint pour un outil d'intelligence concurrentielle sur les marchés publics.

Tu reçois UNIQUEMENT une fiche de faits au format JSON dans le message utilisateur — tu n'as accès à aucun outil, aucune base de données, aucune autre source d'information. Ta seule mission : transformer ces faits en une seule phrase de synthèse, selon exactement ce gabarit :

{GABARIT_STRICT}

Si la fiche ne contient aucun fait (clé "faits" = liste vide), réponds exactement : "Données insuffisantes : <raison>." en remplaçant <raison> par le champ "raison" de la fiche.

Règles absolues, sans exception :
1. N'utilise JAMAIS un nombre, un nom d'entreprise, une date ou un pourcentage qui n'apparaît PAS explicitement dans la fiche de faits fournie. Si une information manque, dis-le explicitement ("non disponible") — ne l'invente jamais.
2. Ne déduis, n'estime, ni n'arrondis aucune valeur toi-même au-delà de ce que le gabarit demande déjà (ex. couverture en %).
3. Ne mentionne jamais une entreprise, un marché ou une source absents de la fiche, même par analogie.
4. Réponds uniquement avec la phrase finale, sans préambule, sans commentaire, sans guillemets autour du texte."""


def _extraire_texte(reponse) -> str:
    for bloc in reponse.content:
        if bloc.type == "text":
            return bloc.text.strip()
    return ""


def _serialiser_fiche(fiche: dict) -> str:
    return json.dumps(fiche, ensure_ascii=False, default=str)


def verbaliser_via_llm(fiche: dict, client=None) -> str:
    """
    Point d'entrée. Retourne toujours un texte valide selon
    verification_mecanique.verifier_texte() — soit généré par le LLM et
    vérifié, soit (dégradation gracieuse) le gabarit déterministe de
    scripts/verbaliser.py si le LLM échoue ou n'est jamais parvenu à
    produire un texte valide en MAX_TENTATIVES essais.

    `client` est injectable pour les tests (éviter un vrai appel réseau
    dans les tests qui n'ont pas besoin d'exercer le LLM réel).
    """
    if not fiche["faits"]:
        # Même raccourci que verbaliser.py : rien à verbaliser de risqué,
        # pas la peine de payer un appel LLM pour une phrase fixe.
        return verbaliser(fiche)

    import anthropic

    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return verbaliser(fiche)  # dégradation gracieuse : pas de clé
        client = anthropic.Anthropic()

    fiche_json = _serialiser_fiche(fiche)
    messages = [{"role": "user", "content": fiche_json}]

    for tentative in range(MAX_TENTATIVES):
        try:
            reponse = client.messages.create(
                model=MODELE_LLM,
                max_tokens=MAX_TOKENS_REPONSE,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
        except (anthropic.APIConnectionError, anthropic.RateLimitError,
                anthropic.APIStatusError, anthropic.AuthenticationError):
            # Réseau, quota, ou clé invalide : jamais un crash côté briefing,
            # même repli que si aucune clé n'était configurée.
            return verbaliser(fiche)

        if reponse.stop_reason == "refusal":
            return verbaliser(fiche)

        texte = _extraire_texte(reponse)
        resultat = verifier_texte(texte, fiche)
        if resultat["valide"]:
            return texte

        # Invalide : on régénère en signalant explicitement ce qui a été
        # rejeté (nombres ET noms d'entreprise), jamais un deuxième essai à
        # l'aveugle.
        messages.append({"role": "assistant", "content": texte})
        messages.append({"role": "user", "content": (
            "Ce texte contient des valeurs absentes de la fiche de faits : "
            f"nombres {resultat['nombres_non_justifies']}, "
            f"noms d'entreprise {resultat['noms_non_justifies']}. Régénère "
            "la phrase en respectant strictement le gabarit et uniquement "
            "les valeurs de la fiche fournie plus haut."
        )})

    # MAX_TENTATIVES épuisées sans texte valide : repli déterministe,
    # jamais un texte non vérifié livré (sujet, section 4 : "publier un
    # chiffre inventé devient structurellement impossible").
    return verbaliser(fiche)


if __name__ == "__main__":
    from scripts.fiche_de_faits import construire_fiche_de_faits

    fiche = construire_fiche_de_faits("11000028800016", "72220000")
    print(verbaliser_via_llm(fiche))
