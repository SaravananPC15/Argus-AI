"""
synthetic_anchor.py — Protocol Synthetic Anchor (Local Search Engine).

Unifies three things that were previously separate FAISS indices/sources
into one conceptual search surface: ingested PDFs (document_processor.py),
your own code's docstrings/comments, and any plain-text notes files you
keep in a notes/ folder. Reuses document_processor's embedder singleton
so this doesn't load a third copy of the sentence-transformer model.

This is a read-only index built by scanning your project -- it doesn't
touch conversation_memory.py's conversation index, which is about
recalling things you *said*, not things you *wrote*.
"""

import os
import glob
import ast
import numpy as np
import faiss
import document_processor  # reuse the embedder singleton

DIMENSION = 384
INDEX_FILE = "argus_anchor.faiss"
TEXT_MAPPING_FILE = "argus_anchor_texts.npy"
NOTES_DIR = "notes"


def _extract_code_comments_and_docstrings(py_file: str):
    entries = []
    try:
        with open(py_file, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=py_file)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                docstring = ast.get_docstring(node)
                if docstring and len(docstring.strip()) > 15:
                    entries.append(f"[{py_file}::{node.name}] {docstring.strip()}")
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#") and len(stripped) > 20:
                entries.append(f"[{py_file}] {stripped.lstrip('#').strip()}")
    except (SyntaxError, OSError):
        pass
    return entries


def _load_notes():
    entries = []
    if not os.path.isdir(NOTES_DIR):
        return entries
    for path in glob.glob(os.path.join(NOTES_DIR, "**", "*.txt"), recursive=True) + \
            glob.glob(os.path.join(NOTES_DIR, "**", "*.md"), recursive=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 40]
            entries.extend(f"[{path}] {p}" for p in paragraphs)
        except OSError:
            continue
    return entries


def rebuild_index():
    """Scans the project's .py files + notes/ folder and rebuilds the
    anchor index from scratch. Call this after adding new notes/code, or
    periodically via a scheduled task."""
    entries = []
    for py_file in glob.glob("*.py"):
        entries.extend(_extract_code_comments_and_docstrings(py_file))
    entries.extend(_load_notes())

    if not entries:
        return 0

    embeddings = document_processor.embedder.encode(entries)
    index = faiss.IndexFlatL2(DIMENSION)
    index.add(np.array(embeddings).astype('float32'))

    faiss.write_index(index, INDEX_FILE)
    np.save(TEXT_MAPPING_FILE, entries)
    return len(entries)


def search(query: str, top_k: int = 5):
    """Searches the anchor index (code comments/docstrings + notes).
    Combine with document_processor.query_documents() for full coverage
    including ingested PDFs."""
    if not os.path.exists(INDEX_FILE):
        rebuild_index()
        if not os.path.exists(INDEX_FILE):
            return []

    index = faiss.read_index(INDEX_FILE)
    saved_texts = np.load(TEXT_MAPPING_FILE, allow_pickle=True).tolist()
    if index.ntotal == 0:
        return []

    query_embedding = document_processor.embedder.encode([query])
    k = min(top_k, index.ntotal)
    distances, indices = index.search(np.array(query_embedding).astype('float32'), k)
    return [saved_texts[i] for i in indices[0] if 0 <= i < len(saved_texts)]


def handle_search_request(query: str) -> str:
    """Entry point for executor.py's 'synthetic_anchor' action."""
    results = search(query, top_k=5)
    if not results:
        return "Nothing in your local notes/code/docs matches that yet, macha. Try Protocol Synthetic Anchor again after adding more notes."
    joined = " | ".join(results[:3])
    return f"Found this in your own project data: {joined}"
