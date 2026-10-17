"""
SpecSense MVP2 — Retrieval demo (Stage C: RAG evidence retrieval, Stage E: cited explanation).

Loads the Chroma collection built by ingest_kb.py, embeds a query with the same
fitted TF-IDF vocabulary, retrieves the top-k most relevant chunks, and prints
them with full citation metadata. Also shows a minimal cited-explanation
template — the shape Stage E's LLM call should follow (evidence first, then a
plain-language explanation that only uses what was retrieved).
"""

import pickle
import chromadb
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # project root (parent of src/)
DB_PATH = str(BASE_DIR / "vector_store" / "chroma_db")
COLLECTION_NAME = "specsense_kb"


def load_query_embedder():
    with open(f"{DB_PATH}/vectorizer.pkl", "rb") as f:
        return pickle.load(f)


def query(collection, vectorizer, question, k=3, collection_filter=None):
    q_vec = vectorizer.transform([question]).toarray().tolist()
    where = {"collection": collection_filter} if collection_filter else None
    results = collection.query(query_embeddings=q_vec, n_results=k, where=where)
    hits = []
    for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
        hits.append({"text": doc, "metadata": meta, "distance": dist})
    return hits


def print_hits(question, hits):
    print(f"\nQuery: {question}")
    for h in hits:
        m = h["metadata"]
        print(f"  [{m['doc_id']} / {m['section_title']}] "
              f"(collection={m['collection']}, confidence={m['confidence']}, "
              f"last_verified={m['last_verified_date']}, distance={h['distance']:.3f})")


def cited_explanation_template(question, hits):
    """
    Illustrates the Stage E shape: retrieved evidence -> plain-language explanation
    that cites doc_id per claim. This is a template, not a real LLM call —
    swap the body for an actual LLM prompt using `hits` as the only allowed
    source of factual claims (the system rule: never invent specs).
    """
    lines = [f"Q: {question}", "", "Evidence retrieved:"]
    for h in hits:
        m = h["metadata"]
        lines.append(f"  - [{m['doc_id']}] {h['text'][:140].strip()}...")
    lines.append("")
    lines.append("(An LLM call would now generate a plain-language answer using only the "
                  "evidence above, citing [doc_id] after each claim, and saying 'unknown' "
                  "for anything not covered by retrieved evidence.)")
    return "\n".join(lines)


if __name__ == "__main__":
    client = chromadb.PersistentClient(path=DB_PATH)
    collection = client.get_collection(COLLECTION_NAME)
    vectorizer = load_query_embedder()

    demo_questions = [
        "Why does RAM matter for running Docker containers?",
        "What does TOPS mean and why does it matter for an AI PC?",
        "Is a laptop RTX 4060 always the same speed as another laptop's RTX 4060?",
        "What GPU and VRAM do I need for Blender rendering?",
    ]

    for q in demo_questions:
        hits = query(collection, vectorizer, q, k=2)
        print_hits(q, hits)

    print("\n" + "=" * 70)
    print("Example cited-explanation template output:")
    print("=" * 70)
    q = demo_questions[0]
    hits = query(collection, vectorizer, q, k=2)
    print(cited_explanation_template(q, hits))
