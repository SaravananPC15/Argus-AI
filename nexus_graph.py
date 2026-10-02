"""
nexus_graph.py — Backing store for Protocol Mind Map Exporter.

A lightweight local graph of "things in your project": documents you've
ingested, git commits, calendar events, and so on. Other protocols call
add_node()/add_edge() as they do their work; mind_map_exporter.py turns
the accumulated graph into an interactive HTML visualization.

This is intentionally a plain JSON file, not a graph database — for a
single-user local project, hundreds/thousands of nodes is plenty and a
real graph DB would be overkill.
"""

import json
import os
import time
import threading

GRAPH_FILE = "nexus_graph.json"
_lock = threading.Lock()


def _load():
    if not os.path.exists(GRAPH_FILE):
        return {"nodes": {}, "edges": []}
    try:
        with open(GRAPH_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"nodes": {}, "edges": []}


def _save(graph):
    with open(GRAPH_FILE, "w") as f:
        json.dump(graph, f, indent=2)


def add_node(node_id: str, label: str, node_type: str, metadata: dict = None):
    """node_type examples: 'document', 'commit', 'event', 'note', 'script'."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("mind_map_exporter"):
            return
    except Exception:
        pass

    with _lock:
        graph = _load()
        graph["nodes"][node_id] = {
            "id": node_id,
            "label": label,
            "type": node_type,
            "metadata": metadata or {},
            "updated_at": time.time(),
        }
        _save(graph)


def add_edge(source_id: str, target_id: str, relation: str = "related_to"):
    with _lock:
        graph = _load()
        # Avoid duplicate edges
        for e in graph["edges"]:
            if e["source"] == source_id and e["target"] == target_id and e["relation"] == relation:
                return
        graph["edges"].append({"source": source_id, "target": target_id, "relation": relation})
        _save(graph)


def get_graph():
    with _lock:
        return _load()


def node_count():
    return len(get_graph()["nodes"])
