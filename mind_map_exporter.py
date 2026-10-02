"""
mind_map_exporter.py — Protocol Mind Map Exporter (Visual Graph Render).

Converts the accumulated nexus_graph.json (documents ingested, git
commits, calendar events, and anything else other protocols have
registered as nodes) into a single self-contained interactive HTML file
using vis-network, so it can be opened on your phone or shared as one
file — no server required to view it.
"""

import os
import json
import nexus_graph

OUTPUT_PATH = "audio_cache/mind_map.html"

TYPE_COLORS = {
    "document": "#58A6FF",
    "commit": "#3FB950",
    "event": "#F778BA",
    "note": "#D29922",
    "script": "#A371F7",
}

_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Argus Nexus — Project Mind Map</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/vis-network.min.js"></script>
<style>
  body {{ margin:0; background:#0E1117; color:#E2E8F0; font-family:-apple-system,sans-serif; }}
  #header {{ padding:14px 20px; border-bottom:1px solid #30363D; }}
  #header h1 {{ margin:0; font-size:1.1em; color:#58A6FF; }}
  #header p {{ margin:4px 0 0; color:#8B949E; font-size:0.85em; }}
  #network {{ width:100vw; height:calc(100vh - 62px); }}
</style>
</head>
<body>
<div id="header">
  <h1>🧠 Argus Nexus — Project Mind Map</h1>
  <p>{node_count} nodes &middot; {edge_count} connections. Drag to explore, scroll to zoom.</p>
</div>
<div id="network"></div>
<script>
  const nodes = new vis.DataSet({nodes_json});
  const edges = new vis.DataSet({edges_json});
  const container = document.getElementById('network');
  const data = {{ nodes, edges }};
  const options = {{
    nodes: {{ shape: 'dot', size: 14, font: {{ color: '#E2E8F0', size: 13 }}, borderWidth: 2 }},
    edges: {{ color: {{ color: '#30363D', highlight: '#58A6FF' }}, smooth: {{ type: 'continuous' }} }},
    physics: {{ solver: 'forceAtlas2Based', stabilization: {{ iterations: 150 }} }},
    interaction: {{ hover: true }}
  }};
  new vis.Network(container, data, options);
</script>
</body>
</html>"""


def export_mind_map() -> str:
    """Entry point for executor.py's 'mind_map_export' action."""
    graph = nexus_graph.get_graph()
    node_list = list(graph["nodes"].values())

    if not node_list:
        return "Nexus graph is empty right now, macha — ingest a document, make a commit, or add a calendar event first, then try again."

    vis_nodes = [
        {
            "id": n["id"],
            "label": n["label"][:40],
            "color": TYPE_COLORS.get(n["type"], "#8B949E"),
            "title": f"{n['type']}: {n['label']}",
        }
        for n in node_list
    ]
    vis_edges = [
        {"from": e["source"], "to": e["target"], "label": e.get("relation", "")}
        for e in graph["edges"]
        if e["source"] in graph["nodes"] and e["target"] in graph["nodes"]
    ]

    html = _TEMPLATE.format(
        node_count=len(vis_nodes),
        edge_count=len(vis_edges),
        nodes_json=json.dumps(vis_nodes),
        edges_json=json.dumps(vis_edges),
    )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        f.write(html)

    return f"Mind map exported, macha — {len(vis_nodes)} nodes, {len(vis_edges)} connections. Saved to {OUTPUT_PATH}, open it on your phone."
