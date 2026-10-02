"""
git_archeologist.py — Protocol Git Archeologist (Visual Branch Traversal).

Instead of a flat `git log`, this walks the commit history that actually
touched a given file (optionally narrowed to a function name via a
simple text search per commit), and renders it as an interactive HTML
graph: each commit is a node, edges point to its parent(s), so you can
see how a file evolved and click back to any point to review or plan a
rollback.

Uses GitPython (already a project dependency).
"""

import os
import time
import git
import nexus_graph

OUTPUT_DIR = "audio_cache"


def _commits_touching(repo, filepath, function_name=None, max_commits=60):
    commits = list(repo.iter_commits(paths=filepath, max_count=max_commits))
    if not function_name:
        return commits

    filtered = []
    for c in commits:
        try:
            diff_text = repo.git.show(c.hexsha, "--", filepath)
        except Exception:
            continue
        if function_name in diff_text:
            filtered.append(c)
    return filtered


def build_commit_graph(filepath: str, function_name: str = None, max_commits: int = 60):
    """Returns {"nodes": [...], "edges": [...]} describing commit history
    for filepath, and also registers the commits into nexus_graph.py so
    they show up in the Mind Map Exporter too."""
    repo = git.Repo(".", search_parent_directories=True)
    commits = _commits_touching(repo, filepath, function_name, max_commits)

    nodes, edges = [], []
    seen = set()
    for c in commits:
        node_id = c.hexsha[:10]
        if node_id in seen:
            continue
        seen.add(node_id)
        nodes.append({
            "id": node_id,
            "message": c.message.strip().split("\n")[0][:80],
            "author": str(c.author.name),
            "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(c.committed_date)),
        })
        nexus_graph.add_node(f"commit:{node_id}", c.message.strip().split("\n")[0][:60], "commit",
                              {"file": filepath, "author": str(c.author.name)})
        for parent in c.parents:
            parent_id = parent.hexsha[:10]
            edges.append({"source": node_id, "target": parent_id})
            nexus_graph.add_edge(f"commit:{node_id}", f"commit:{parent_id}", "parent_of")

    return {"file": filepath, "function": function_name, "nodes": nodes, "edges": edges}


def _render_html(graph_data: dict) -> str:
    """Builds a standalone HTML file with a simple SVG commit-chain
    visualization (newest at top, lines to parents) — no external CDN
    dependency needed since it's just a linear/branching chain, not a
    full force-directed layout."""
    nodes = graph_data["nodes"]
    edges = graph_data["edges"]
    node_index = {n["id"]: i for i, n in enumerate(nodes)}

    row_height = 90
    svg_height = max(200, len(nodes) * row_height + 40)
    svg_nodes = []
    svg_edges = []

    for i, n in enumerate(nodes):
        y = 40 + i * row_height
        svg_nodes.append(f"""
        <g class="commit-node" transform="translate(60,{y})">
            <circle r="10" fill="#3FB950" stroke="#0E1117" stroke-width="2"/>
            <text x="24" y="-6" class="commit-hash">{n['id']}</text>
            <text x="24" y="14" class="commit-msg">{n['message']}</text>
            <text x="24" y="32" class="commit-meta">{n['author']} &middot; {n['date']}</text>
        </g>
        """)

    for e in edges:
        if e["source"] in node_index and e["target"] in node_index:
            y1 = 40 + node_index[e["source"]] * row_height
            y2 = 40 + node_index[e["target"]] * row_height
            svg_edges.append(f'<line x1="60" y1="{y1}" x2="60" y2="{y2}" stroke="#30363D" stroke-width="2"/>')

    title = f"{graph_data['file']}" + (f" — function: {graph_data['function']}" if graph_data.get("function") else "")

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Git Archeologist — {title}</title>
<style>
body {{ background:#0E1117; color:#E2E8F0; font-family:-apple-system,sans-serif; padding:20px; }}
h1 {{ font-size:1.2em; color:#3FB950; }}
.commit-hash {{ fill:#58A6FF; font-family:monospace; font-size:13px; }}
.commit-msg {{ fill:#E2E8F0; font-size:14px; }}
.commit-meta {{ fill:#8B949E; font-size:11px; }}
</style></head>
<body>
<h1>🪦 Protocol Git Archeologist — {title}</h1>
<p>{len(nodes)} commits found. Newest first, lines trace parent commits.</p>
<svg width="700" height="{svg_height}" xmlns="http://www.w3.org/2000/svg">
{''.join(svg_edges)}
{''.join(svg_nodes)}
</svg>
</body></html>"""


def generate_report(filepath: str, function_name: str = None) -> str:
    """Entry point for executor.py's 'git_archeology' action. Builds the
    graph, writes an HTML report, and returns a spoken-style summary."""
    try:
        graph_data = build_commit_graph(filepath, function_name)
    except git.exc.InvalidGitRepositoryError:
        return "Bro, the current directory isn't a valid Git repository."
    except Exception as e:
        print(f"[Git Archeologist Error]: {e}")
        return "I hit a snag digging through the git history."

    if not graph_data["nodes"]:
        return f"No commit history found for {filepath}" + (f" touching '{function_name}'" if function_name else "") + "."

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "git_archeology_report.html")
    with open(output_path, "w") as f:
        f.write(_render_html(graph_data))

    return (f"Dug up {len(graph_data['nodes'])} commits for {filepath}. "
            f"Report's ready at {output_path}, macha — open it to see the rollback map.")
