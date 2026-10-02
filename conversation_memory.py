"""
conversation_memory.py — Feature 3: Persistent, queryable long-term memory.

memory.py / database.py already handle explicit "remember that X is Y"
facts. This module handles the other kind of memory: being able to
semantically recall *past conversations* even when the user never
explicitly asked Argus to memorize anything.

It reuses document_processor's sentence-transformer embedder (so we
don't load a second ~80MB model into RAM) and keeps a separate FAISS
index just for conversation turns, so document RAG and conversation
recall don't pollute each other's search results.
"""

import os
import numpy as np
import faiss

import document_processor  # reuse the already-loaded embedder singleton

DIMENSION = 384
INDEX_FILE = "argus_conversations.faiss"
TEXT_MAPPING_FILE = "argus_conversations_texts.npy"

# Only index substantive turns — short filler ("ok", "yes") isn't useful
# to recall later and just adds noise to the vector search.
MIN_CHARS_TO_INDEX = 12


def index_turn(role: str, content: str):
    """Embeds a single conversation turn and appends it to the FAISS index."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("semantic_memory"):
            return
    except Exception:
        pass

    if not content or len(content.strip()) < MIN_CHARS_TO_INDEX:
        return
    try:
        embedding = document_processor.embedder.encode([content])

        if os.path.exists(INDEX_FILE):
            index = faiss.read_index(INDEX_FILE)
            saved_texts = np.load(TEXT_MAPPING_FILE, allow_pickle=True).tolist()
        else:
            index = faiss.IndexFlatL2(DIMENSION)
            saved_texts = []

        index.add(np.array(embedding).astype('float32'))
        saved_texts.append({"role": role, "content": content})

        faiss.write_index(index, INDEX_FILE)
        np.save(TEXT_MAPPING_FILE, saved_texts)
    except Exception as e:
        print(f"[Conversation Memory Error] Failed to index turn: {e}")


def semantic_recall(query: str, top_k: int = 3, min_chars: int = 6):
    """
    Searches past conversation turns for ones semantically related to
    `query`. Returns a list of {"role", "content"} dicts, most relevant
    first. Returns an empty list if there's no index yet, the query is
    too short to embed meaningfully, or the "semantic_memory" toggle is off.
    """
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("semantic_memory"):
            return []
    except Exception:
        pass

    if not query or len(query.strip()) < min_chars:
        return []
    if not os.path.exists(INDEX_FILE):
        return []

    try:
        index = faiss.read_index(INDEX_FILE)
        saved_texts = np.load(TEXT_MAPPING_FILE, allow_pickle=True).tolist()
        if index.ntotal == 0:
            return []

        query_embedding = document_processor.embedder.encode([query])
        k = min(top_k, index.ntotal)
        distances, indices = index.search(np.array(query_embedding).astype('float32'), k)

        results = [saved_texts[idx] for idx in indices[0] if 0 <= idx < len(saved_texts)]
        return results
    except Exception as e:
        print(f"[Conversation Memory Error] Failed semantic recall: {e}")
        return []
