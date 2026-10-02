#!/usr/bin/env python3
"""
graph_sync_service.py — launch.py entry point for Protocol Peer-to-Peer
Graph Sync.

Runs both halves needed to actually PARTICIPATE in a sync (not just
initiate one): answering other devices' discovery broadcasts, and
serving this device's current graph to whoever connects. The
"graph_sync_now" action (executor.py) does the PULLING side on demand
from a running chat session; this service is what makes pulling FROM
this device possible at all, and needs to be running on every device
you want included.
"""
import os
import threading

import graph_sync
import nexus_graph

if __name__ == "__main__":
    passphrase = os.environ.get("ARGUS_GRAPH_SYNC_PASSPHRASE")
    if not passphrase:
        print("[Graph Sync Service] ARGUS_GRAPH_SYNC_PASSPHRASE isn't set -- see SETUP.md. Exiting.")
    else:
        threading.Thread(target=graph_sync.run_discovery_responder, daemon=True).start()
        graph_sync.serve_graph_sync(nexus_graph.get_graph, passphrase)
