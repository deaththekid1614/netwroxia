#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════════
# NETWROXIA — Stage 4: RAG Document Ingestion
# Chunks + embeds knowledge base → ChromaDB vector store
# ═══════════════════════════════════════════════════════════════════════════════

import os
import sys

# ── FIX 1: Disable ChromaDB telemetry ──────────────────────────────────────
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# ── FIX 2: Override sqlite3 BEFORE any other import ──────────────────────────
try:
    import pysqlite3
    sys.modules["sqlite3"] = pysqlite3
    _SQLITE_FIXED = True
except ImportError:
    _SQLITE_FIXED = False

# ── CONFIG ───────────────────────────────────────────────────────────────────
from pathlib import Path
BASE_DIR = Path(__file__).parent.parent.resolve()
KB_DIR = BASE_DIR / "knowledge_base"
DB_DIR = BASE_DIR / "rag" / "chroma_db"
COLLECTION_NAME = "netwroxia_kb"

# ── IMPORTS ──────────────────────────────────────────────────────────────────
import json
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb

# ── HELPERS ────────────────────────────────────────────────────────────────────
def load_documents(kb_dir: Path):
    docs = []
    for ext in ["*.md", "*.json"]:
        for filepath in kb_dir.rglob(ext):
            rel_path = filepath.relative_to(kb_dir)
            print(f"  📄 Loading: {rel_path}")
            content = filepath.read_text(encoding="utf-8")
            meta = {
                "source": str(rel_path),
                "filename": filepath.name,
                "type": filepath.suffix.lstrip("."),
            }
            if filepath.suffix == ".json":
                try:
                    data = json.loads(content)
                    meta["incident_id"] = data.get("incident_id", "N/A")
                    meta["severity"] = data.get("severity", "N/A")
                    meta["title"] = data.get("title", "N/A")
                    meta["affected_users"] = str(data.get("affected_users", "N/A"))
                except json.JSONDecodeError:
                    pass
            docs.append({"content": content, "metadata": meta})
    return docs


def chunk_documents(docs, chunk_size=512, chunk_overlap=64):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = []
    for doc in docs:
        texts = splitter.split_text(doc["content"])
        for i, text in enumerate(texts):
            chunk_meta = doc["metadata"].copy()
            chunk_meta["chunk_index"] = i
            chunks.append({
                "id": f"{chunk_meta['source']}_chunk_{i}",
                "text": text.strip(),
                "metadata": chunk_meta,
            })
    return chunks


def ingest_to_chromadb(chunks, db_dir: Path):
    print(f"\n{'='*60}")
    print("  STORING IN CHROMADB")
    print(f"{'='*60}")
    
    if _SQLITE_FIXED:
        print("  🔧 Using pysqlite3-binary override")
    else:
        print("  ⚠️  Using system sqlite3 (may fail if < 3.35.0)")
    
    settings = chromadb.Settings(
        anonymized_telemetry=False,
        persist_directory=str(db_dir),
    )
    
    client = chromadb.PersistentClient(path=str(db_dir), settings=settings)
    
    # CORRECT API: chromadb.utils.embedding_functions (lowercase)
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    embedding_fn = DefaultEmbeddingFunction()
    
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"description": "Netwroxia NOC Knowledge Base"},
    )
    
    existing = collection.count()
    if existing > 0:
        print(f"  🗑️  Clearing {existing} existing chunks...")
        collection.delete(where={})
    
    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        collection.add(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )
        print(f"  ✅ Batch {i//batch_size + 1}: {len(batch)} chunks stored")
    
    total = collection.count()
    print(f"\n  🎉 Total chunks in ChromaDB: {total}")
    return client, collection


def test_retrieval(collection, query: str, n_results: int = 3):
    print(f"\n{'='*60}")
    print(f"  TEST RETRIEVAL: '{query}'")
    print(f"{'='*60}")
    
    results = collection.query(
        query_texts=[query],
        n_results=n_results,
    )
    
    for i, (doc, meta, dist) in enumerate(zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    )):
        print(f"\n  [{i+1}] Score: {dist:.4f} | Source: {meta['source']}")
        preview = doc[:200].replace("\n", " ")
        print(f"      {preview}...")


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  NETWROXIA — RAG Document Ingestion")
    print("=" * 60)
    print(f"\n  KB Directory: {KB_DIR}")
    print(f"  DB Directory: {DB_DIR}")
    
    print(f"\n{'='*60}")
    print("  LOADING DOCUMENTS")
    print(f"{'='*60}")
    docs = load_documents(KB_DIR)
    print(f"\n  📚 Total documents loaded: {len(docs)}")
    
    if not docs:
        print("  ⚠️  No documents found!")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print("  CHUNKING DOCUMENTS")
    print(f"{'='*60}")
    chunks = chunk_documents(docs)
    print(f"  ✂️  Total chunks created: {len(chunks)}")
    
    client, collection = ingest_to_chromadb(chunks, DB_DIR)
    
    test_retrieval(collection, "BGP peer down route flapping")
    test_retrieval(collection, "ATM transaction failure CBS timeout")
    
    print(f"\n{'='*60}")
    print("  ✅ INGESTION COMPLETE")
    print(f"{'='*60}")
    print(f"\n  ChromaDB location: {DB_DIR}")
    print("  Next: python3 copilot/llm/inference.py")


if __name__ == "__main__":
    main() 