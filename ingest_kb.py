"""
SpecSense MVP2 — Knowledge base ingestion pipeline.

Chunks the markdown knowledge base (hardware glossary, workload requirements,
buying education), embeds each chunk, and stores it in a persistent Chroma
collection with citation metadata (source doc, collection, confidence, dates).

Embedding choice: this environment has no outbound access to model hubs
(Hugging Face etc.), so a real sentence-transformer model can't be downloaded
here. This script uses scikit-learn's TF-IDF vectorizer as an offline,
dependency-free stand-in embedding so the pipeline is runnable end-to-end
right now. Swap `embed_chunks()` for `sentence-transformers`
(e.g. 'all-MiniLM-L6-v2') or an embedding API once the target environment has
network access — the rest of the pipeline (chunking, metadata, Chroma storage,
retrieval, citations) does not need to change.
"""

import os
import re
import glob
import pickle
import chromadb
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer

BASE_DIR = Path(__file__).resolve().parent.parent  # project root (parent of src/)
KB_ROOT = str(BASE_DIR / "knowledge_base")
DB_PATH = str(BASE_DIR / "vector_store" / "chroma_db")
COLLECTION_NAME = "specsense_kb"
EMBED_DIM = 384  # capped TF-IDF vocabulary size, chosen to resemble a typical embedding width


def parse_frontmatter(text):
    """Very small YAML front-matter parser for our controlled doc format."""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm_text, body = m.groups()
    meta = {}
    for line in fm_text.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body


def chunk_by_heading(body):
    """Split a doc's body into chunks at each '## ' heading. Each chunk keeps its heading."""
    parts = re.split(r"\n(?=## )", body.strip())
    chunks = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        heading_match = re.match(r"^##\s+(.*)", part)
        heading = heading_match.group(1).strip() if heading_match else "Untitled section"
        chunks.append({"heading": heading, "text": part})
    return chunks


def load_all_chunks():
    all_chunks = []
    md_files = sorted(glob.glob(f"{KB_ROOT}/**/*.md", recursive=True))
    for path in md_files:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        meta, body = parse_frontmatter(raw)
        for i, c in enumerate(chunk_by_heading(body)):
            chunk_id = f"{meta.get('doc_id', os.path.basename(path))}__chunk{i:02d}"
            all_chunks.append({
                "id": chunk_id,
                "text": c["text"],
                "metadata": {
                    "collection": meta.get("collection", "unknown"),
                    "doc_id": meta.get("doc_id", os.path.basename(path)),
                    "section_title": c["heading"],
                    "source_type": meta.get("source_type", "unknown"),
                    "source_date": meta.get("source_date", "unknown"),
                    "last_verified_date": meta.get("last_verified_date", "unknown"),
                    "confidence": meta.get("confidence", "unknown"),
                    "file_path": path,
                }
            })
    return all_chunks


def embed_chunks(chunks, vectorizer=None):
    """Offline TF-IDF embedding stand-in. See module docstring for the upgrade path."""
    texts = [c["text"] for c in chunks]
    if vectorizer is None:
        vectorizer = TfidfVectorizer(max_features=EMBED_DIM, stop_words="english")
        vectors = vectorizer.fit_transform(texts)
    else:
        vectors = vectorizer.transform(texts)
    return vectors.toarray().tolist(), vectorizer


def build_store():
    chunks = load_all_chunks()
    if not chunks:
        raise SystemExit(f"No knowledge base docs found: put the .md files under {KB_ROOT}")
    embeddings, vectorizer = embed_chunks(chunks)

    client = chromadb.PersistentClient(path=DB_PATH)
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)

    collection.add(
        ids=[c["id"] for c in chunks],
        embeddings=embeddings,
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )

    # Persist the fitted vectorizer (vocabulary + idf weights) so queries embed consistently later.
    with open(f"{DB_PATH}/vectorizer.pkl", "wb") as f:
        pickle.dump(vectorizer, f)

    print(f"Ingested {len(chunks)} chunks from {len(set(c['metadata']['doc_id'] for c in chunks))} documents "
          f"into Chroma collection '{COLLECTION_NAME}' at {DB_PATH}")
    by_collection = {}
    for c in chunks:
        by_collection.setdefault(c["metadata"]["collection"], 0)
        by_collection[c["metadata"]["collection"]] += 1
    for k, v in by_collection.items():
        print(f"  - {k}: {v} chunks")

    return collection, vectorizer


if __name__ == "__main__":
    build_store()
