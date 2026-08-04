"""
Recherche de marchés similaires par embedding (sujet, section 4 : "rapprocher
les objets de marché similaires, car les codes CPV sont mal saisis" ;
section 8, piège "CPV mal saisi -> complété par similarité").

Distance cosinus (pgvector, opérateur `<=>`) contre `marches.objet_embedding`
(généré par scripts/generer_embeddings_marches.py). Retourne toujours le
score de similarité — jamais un rapprochement présenté comme aussi certain
qu'une correspondance exacte de CPV, même principe que `score_confiance`
en résolution d'identité (scripts/resolution_identite.py).

Usage :
    python scripts/marches_similaires.py
"""
import sys

sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine

MODELE = "paraphrase-multilingual-MiniLM-L12-v2"

_modele_charge = None


def _obtenir_modele():
    global _modele_charge
    if _modele_charge is None:
        from sentence_transformers import SentenceTransformer
        _modele_charge = SentenceTransformer(MODELE)
    return _modele_charge


def trouver_marches_similaires(
    uid: str | None = None,
    texte: str | None = None,
    limite: int = 10,
    exclure_meme_cpv: bool = False,
) -> list[dict]:
    """
    Trouve les marchés dont l'objet est sémantiquement proche d'un marché
    de référence (uid) ou d'un texte libre. exclure_meme_cpv=True isole les
    cas où le rapprochement se fait malgré un CPV différent — exactement le
    piège "CPV mal saisi" du sujet (section 8).

    Un et un seul de (uid, texte) doit être fourni.
    """
    if (uid is None) == (texte is None):
        raise ValueError("Fournir soit uid, soit texte, pas les deux ni aucun.")

    engine = get_engine()

    with engine.connect() as connexion:
        if uid is not None:
            reference = connexion.execute(text(
                "SELECT objet_embedding, code_cpv FROM marches WHERE uid = :uid"
            ), {"uid": uid}).fetchone()
            if reference is None or reference[0] is None:
                return []
            embedding_reference, cpv_reference = reference
        else:
            modele = _obtenir_modele()
            embedding_reference = str(modele.encode([texte], normalize_embeddings=True)[0].tolist())
            cpv_reference = None

        condition_cpv = ""
        parametres = {"embedding": str(embedding_reference), "limite": limite}
        if uid is not None:
            condition_cpv = "AND uid != :uid_exclu"
            parametres["uid_exclu"] = uid
        if exclure_meme_cpv and cpv_reference:
            condition_cpv += " AND (code_cpv IS NULL OR code_cpv != :cpv_reference)"
            parametres["cpv_reference"] = cpv_reference

        resultats = connexion.execute(text(f"""
            SELECT uid, objet, code_cpv, siret_acheteur,
                   1 - (objet_embedding <=> :embedding) AS similarite
            FROM marches
            WHERE objet_embedding IS NOT NULL
            {condition_cpv}
            ORDER BY objet_embedding <=> :embedding
            LIMIT :limite
        """), parametres).mappings().all()

    return [dict(r) for r in resultats]


if __name__ == "__main__":
    # Exemple : marchés similaires à un marché réel du périmètre (conseil
    # en systèmes informatiques, Cour des Comptes), y compris ceux dont le
    # CPV diffère (démonstration du cas "CPV mal saisi").
    with get_engine().connect() as connexion:
        exemple = connexion.execute(text(
            "SELECT uid, objet FROM marches WHERE objet_embedding IS NOT NULL "
            "ORDER BY date_notification DESC LIMIT 1"
        )).fetchone()

    if exemple:
        print(f"Référence : {exemple.uid} — {exemple.objet[:80]}")
        for r in trouver_marches_similaires(uid=exemple.uid, limite=5):
            print(f"  {r['similarite']:.2f} | CPV {r['code_cpv']} | {r['objet'][:80]}")
    else:
        print("Aucun marché avec embedding trouvé — lancer scripts/generer_embeddings_marches.py d'abord.")
