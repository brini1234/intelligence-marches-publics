"""
Génère les embeddings sémantiques des objets de marché (sujet, section 4 :
"les vecteurs ne servent qu'à un endroit : rapprocher les objets de marché
similaires, car les codes CPV sont mal saisis" ; section 6, S4).

Modèle local (sentence-transformers), pas d'appel API : aucune passerelle
LLM n'est configurée dans ce projet (cf. README), et un modèle local évite
toute dépendance à une clé externe pour une tâche qui n'a pas besoin de la
qualité d'un grand modèle (rapprochement de courtes descriptions de
marché, pas de génération de texte).

Modèle : paraphrase-multilingual-MiniLM-L12-v2 (384 dimensions, léger,
tourne en CPU en quelques minutes sur l'ensemble du périmètre). Idempotent :
ne recalcule que les lignes sans embedding (uid nouveaux depuis la dernière
exécution, ex. après un nouveau construire_gold_marches.py).

Usage :
    python scripts/generer_embeddings_marches.py
"""
import sys

sys.path.append(".")

from sqlalchemy import text

from db.connection import get_engine

MODELE = "paraphrase-multilingual-MiniLM-L12-v2"
TAILLE_LOT = 256


def generer_embeddings_marches():
    from sentence_transformers import SentenceTransformer

    engine = get_engine()

    with engine.connect() as connexion:
        lignes = connexion.execute(text("""
            SELECT uid, objet FROM marches
            WHERE objet_embedding IS NULL AND objet IS NOT NULL AND objet <> ''
        """)).fetchall()

    if not lignes:
        print("Aucun marché sans embedding à traiter.")
        return

    print(f"{len(lignes)} marché(s) à encoder avec {MODELE} ...")
    print("Chargement du modèle (téléchargé une seule fois, ~470 Mo) ...")
    modele = SentenceTransformer(MODELE)

    uids = [uid for uid, _ in lignes]
    objets = [objet for _, objet in lignes]

    with engine.begin() as connexion:
        for debut in range(0, len(objets), TAILLE_LOT):
            lot_uids = uids[debut:debut + TAILLE_LOT]
            lot_objets = objets[debut:debut + TAILLE_LOT]
            embeddings = modele.encode(lot_objets, show_progress_bar=False, normalize_embeddings=True)

            for uid, embedding in zip(lot_uids, embeddings):
                connexion.execute(text("""
                    UPDATE marches SET objet_embedding = :embedding WHERE uid = :uid
                """), {"uid": uid, "embedding": str(embedding.tolist())})

            print(f"  {min(debut + TAILLE_LOT, len(objets))}/{len(objets)} encodé(s)")

    with engine.begin() as connexion:
        print("Création de l'index HNSW (après peuplement, comme l'index trigram SIRENE) ...")
        connexion.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_marches_objet_embedding "
            "ON marches USING hnsw (objet_embedding vector_cosine_ops)"
        ))
        nb_total = connexion.execute(text("SELECT COUNT(*) FROM marches")).scalar()
        nb_avec_embedding = connexion.execute(text(
            "SELECT COUNT(*) FROM marches WHERE objet_embedding IS NOT NULL"
        )).scalar()

    print(f"\n✅ Embeddings générés. {nb_avec_embedding}/{nb_total} marché(s) couvert(s) "
          f"({nb_avec_embedding / nb_total:.0%}).")


if __name__ == "__main__":
    generer_embeddings_marches()
