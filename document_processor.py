import fitz  # PyMuPDF
import faiss
import numpy as np
import os
import json
import time
from sentence_transformers import SentenceTransformer

# Load ultra-lightweight Hugging Face embedding model (~80MB RAM)
print("[System] Loading Hugging Face Embedding Engine...")
embedder = SentenceTransformer('all-MiniLM-L6-v2')
DIMENSION = 384
INDEX_FILE = "argus_docs.faiss"
TEXT_MAPPING_FILE = "argus_docs_texts.npy"
MANIFEST_FILE = "argus_docs_manifest.json"  # Feature 10: tracks which files were ingested


def _load_manifest():
    if not os.path.exists(MANIFEST_FILE):
        return []
    try:
        with open(MANIFEST_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_manifest(manifest):
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)


def list_ingested_documents():
    """Feature 10: returns the manifest of every document ingested so far,
    so a web/dashboard UI can show what's actually in the RAG library."""
    return _load_manifest()


def ingest_pdf(pdf_path):
    """Reads a PDF, chunks it, embeds it via Hugging Face, and saves to FAISS."""
    print(f"[Document Matrix] Ingesting {pdf_path}...")
    try:
        doc = fitz.open(pdf_path)
        text_chunks = []
        
        # Extract and chunk text by paragraph
        for page in doc:
            text = page.get_text()
            paragraphs = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 50]
            text_chunks.extend(paragraphs)
            
        print(f"[Document Matrix] Generated {len(text_chunks)} data chunks. Embedding now...")
        
        # Convert text to mathematical vectors
        embeddings = embedder.encode(text_chunks)
        
        # Load existing database or create a new one
        if os.path.exists(INDEX_FILE):
            index = faiss.read_index(INDEX_FILE)
            saved_texts = np.load(TEXT_MAPPING_FILE, allow_pickle=True).tolist()
        else:
            index = faiss.IndexFlatL2(DIMENSION)
            saved_texts = []
            
        # Add new knowledge to the matrix
        index.add(np.array(embeddings).astype('float32'))
        saved_texts.extend(text_chunks)
        
        faiss.write_index(index, INDEX_FILE)
        np.save(TEXT_MAPPING_FILE, saved_texts)

        # Feature 10: record this ingestion in the manifest so the library
        # UI can show filenames, not just an opaque vector count.
        manifest = _load_manifest()
        manifest.append({
            "filename": os.path.basename(pdf_path),
            "chunk_count": len(text_chunks),
            "ingested_at": time.time(),
        })
        _save_manifest(manifest)

        try:
            import nexus_graph
            nexus_graph.add_node(f"document:{os.path.basename(pdf_path)}", os.path.basename(pdf_path), "document",
                                  {"chunk_count": len(text_chunks)})
        except Exception:
            pass

        print("[Document Matrix] Knowledge assimilated successfully.")
        return True
        
    except Exception as e:
        print(f"[Document Matrix Error]: {e}")
        return False

def query_documents(question, top_k=2):
    """Searches the FAISS vault for the most relevant paragraphs."""
    if not os.path.exists(INDEX_FILE):
        return None
        
    index = faiss.read_index(INDEX_FILE)
    saved_texts = np.load(TEXT_MAPPING_FILE, allow_pickle=True).tolist()
    
    # Convert user question to vector and search
    query_embedding = embedder.encode([question])
    distances, indices = index.search(np.array(query_embedding).astype('float32'), top_k)
    
    # Retrieve the raw text paragraphs
    results = [saved_texts[idx] for idx in indices[0] if idx != -1]
    return " ".join(results)