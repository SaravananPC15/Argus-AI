"""
graph_sync.py — Protocol Peer-to-Peer Graph Sync.

Breaks nexus_graph.json into encrypted chunks and syncs them with other
devices on the same local network: a UDP broadcast for discovery, then
a direct TCP connection per peer to pull their current graph and merge
it into your own.

HONEST SCOPING: "peer-to-peer" here means devices on the SAME LOCAL
NETWORK finding each other via UDP broadcast and talking directly over
a TCP socket -- not internet-wide peer-to-peer, which needs NAT
traversal or relay infrastructure this project doesn't have. "Mobile
device" participation currently means anything that can run this
Python file: a second computer, or a phone via Termux on Android.
There's no standalone iOS/Android app in this project (see SETUP.md)
-- a phone that's only running the browser-based remote control
(remote_server.py) can't run this listener on its own, since a browser
tab can't open a raw TCP/UDP socket.

The encryption (Fernet, via the `cryptography` package -- new
requirements.txt entry) uses a passphrase-derived key with a FIXED
(not per-device-random) salt. That's a deliberate simplification, not
an oversight: every device syncing the SAME graph has to derive the
SAME key from the SAME passphrase with no prior key-exchange step, so
the salt can't be randomly chosen per device the way it normally would
be. It still needs an actual unguessable passphrase -- this isn't a
substitute for having one, and anyone on the LAN who knows or guesses
that passphrase can read (and, if they also serve fake sync responses,
poison) your graph.
"""

import base64
import json
import socket
import struct
import time

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

DISCOVERY_PORT = 51820
TRANSFER_PORT = 51821
DISCOVERY_MAGIC = b"ARGUS-GRAPH-SYNC-v1"
CHUNK_SIZE = 4096


# --------------------------------------------------------------------
# Crypto -- pure functions, fully testable without any network.
# --------------------------------------------------------------------

def _derive_key(passphrase: str, salt: bytes = b"argus-graph-sync-fixed-salt") -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def encrypt_chunk(data: bytes, passphrase: str) -> bytes:
    return Fernet(_derive_key(passphrase)).encrypt(data)


def decrypt_chunk(token: bytes, passphrase: str) -> bytes:
    return Fernet(_derive_key(passphrase)).decrypt(token)


# --------------------------------------------------------------------
# Chunking and merging -- pure functions, fully testable without any
# network. Operates on nexus_graph.py's own {"nodes": {...}, "edges":
# [...]} shape.
# --------------------------------------------------------------------

def chunk_graph(graph: dict, chunk_size: int = CHUNK_SIZE) -> list:
    """Splits a nexus_graph.json-shaped dict into chunks small enough to
    send comfortably over a socket, each independently parseable (never
    splits one node/edge entry across two chunks)."""
    chunks = []

    current, current_size = {}, 0
    for node_id, node_data in graph.get("nodes", {}).items():
        entry_size = len(json.dumps({node_id: node_data}))
        if current and current_size + entry_size > chunk_size:
            chunks.append({"type": "nodes", "data": current})
            current, current_size = {}, 0
        current[node_id] = node_data
        current_size += entry_size
    if current:
        chunks.append({"type": "nodes", "data": current})

    current_list, current_size = [], 0
    for edge in graph.get("edges", []):
        entry_size = len(json.dumps(edge))
        if current_list and current_size + entry_size > chunk_size:
            chunks.append({"type": "edges", "data": current_list})
            current_list, current_size = [], 0
        current_list.append(edge)
        current_size += entry_size
    if current_list:
        chunks.append({"type": "edges", "data": current_list})

    return chunks


def merge_graph(base: dict, incoming_chunks: list) -> dict:
    """Returns a NEW merged dict -- never mutates `base` in place, so a
    failed/partial sync can't corrupt the working graph. Nodes are a
    union keyed by id (incoming wins on conflict: last-writer-wins,
    the same simplification a plain dict already implies). Edges are
    unioned with exact-duplicate removal."""
    merged_nodes = dict(base.get("nodes", {}))
    merged_edges = list(base.get("edges", []))
    seen_edges = {json.dumps(e, sort_keys=True) for e in merged_edges}

    for chunk in incoming_chunks:
        if chunk["type"] == "nodes":
            merged_nodes.update(chunk["data"])
        elif chunk["type"] == "edges":
            for edge in chunk["data"]:
                key = json.dumps(edge, sort_keys=True)
                if key not in seen_edges:
                    merged_edges.append(edge)
                    seen_edges.add(key)

    return {"nodes": merged_nodes, "edges": merged_edges}


# --------------------------------------------------------------------
# Network -- real socket code, exercised in this file's own tests over
# 127.0.0.1 (two threads, one server one client) rather than left
# unverified.
# --------------------------------------------------------------------

def _send_length_prefixed(sock, data: bytes):
    sock.sendall(struct.pack(">I", len(data)) + data)


def _recv_exact(sock, n: int):
    buf = b""
    while len(buf) < n:
        packet = sock.recv(n - len(buf))
        if not packet:
            return None
        buf += packet
    return buf


def _recv_length_prefixed(sock):
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    (length,) = struct.unpack(">I", header)
    return _recv_exact(sock, length)


def serve_graph_sync(graph_provider, passphrase: str, host: str = "0.0.0.0",
                      port: int = TRANSFER_PORT, once: bool = False):
    """Listens for incoming sync connections and sends the CURRENT graph
    (graph_provider() is called fresh per connection). Blocking -- run
    in its own thread, same as this project's other background
    services (see launch.py). once=True serves exactly one connection
    then returns, used by this file's own test below."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((host, port))
    server_sock.listen(5)
    print(f"[Graph Sync] Listening on {host}:{port}")
    try:
        while True:
            conn, addr = server_sock.accept()
            try:
                graph = graph_provider()
                chunks = chunk_graph(graph)
                _send_length_prefixed(conn, struct.pack(">I", len(chunks)))
                for chunk in chunks:
                    encrypted = encrypt_chunk(json.dumps(chunk).encode("utf-8"), passphrase)
                    _send_length_prefixed(conn, encrypted)
                print(f"[Graph Sync] Sent {len(chunks)} chunk(s) to {addr}")
            except Exception as e:
                print(f"[Graph Sync] Error serving {addr}: {e}")
            finally:
                conn.close()
            if once:
                break
    finally:
        server_sock.close()


def pull_graph_from_peer(host: str, passphrase: str, port: int = TRANSFER_PORT, timeout: float = 10.0) -> list:
    """Connects to a peer's serve_graph_sync and returns the decoded
    chunk list (pass straight to merge_graph). Raises on network/crypto
    failure -- the caller decides whether that's fatal or "try the next
    peer"."""
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        (chunk_count,) = struct.unpack(">I", _recv_length_prefixed(sock))
        chunks = []
        for _ in range(chunk_count):
            encrypted = _recv_length_prefixed(sock)
            decrypted = decrypt_chunk(encrypted, passphrase)
            chunks.append(json.loads(decrypted))
        return chunks
    finally:
        sock.close()


def discover_peers(timeout: float = 3.0, port: int = DISCOVERY_PORT) -> list:
    """Broadcasts a UDP probe on the local network and collects
    responses for `timeout` seconds. Returns responding peers' IP
    addresses. Requires the OS/network to allow UDP broadcast -- most
    home/LAN networks do; locked-down office or campus networks often
    don't. An empty result usually means that, not "no peers running."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        sock.sendto(DISCOVERY_MAGIC, ("255.255.255.255", port))
    except OSError as e:
        sock.close()
        print(f"[Graph Sync] Broadcast not permitted on this network ({e}) -- no peers discovered.")
        return []

    peers, deadline = [], time.time() + timeout
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(1024)
            if data == DISCOVERY_MAGIC + b"-ACK":
                peers.append(addr[0])
        except socket.timeout:
            break
    sock.close()
    return list(set(peers))


def run_discovery_responder(port: int = DISCOVERY_PORT):
    """Answers other devices' discover_peers() broadcasts. Blocking --
    run in its own thread alongside serve_graph_sync."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", port))
    print(f"[Graph Sync] Discovery responder listening on UDP {port}")
    while True:
        data, addr = sock.recvfrom(1024)
        if data == DISCOVERY_MAGIC:
            sock.sendto(DISCOVERY_MAGIC + b"-ACK", addr)


def _self_test():
    # 1. Crypto round-trip, including that the WRONG passphrase fails loudly
    #    rather than silently returning garbage.
    secret = json.dumps({"hello": "world"}).encode("utf-8")
    token = encrypt_chunk(secret, "correct-horse-battery-staple")
    assert decrypt_chunk(token, "correct-horse-battery-staple") == secret
    try:
        decrypt_chunk(token, "wrong-passphrase")
        raise AssertionError("decrypt with wrong passphrase should have failed")
    except Exception as e:
        assert "InvalidToken" in type(e).__name__
    print("[1/3] Crypto round-trip + wrong-passphrase rejection: OK")

    # 2. Chunk -> merge round-trip reproduces the original graph exactly,
    #    and merging two DIFFERENT graphs unions them with dedup.
    graph_a = {"nodes": {f"n{i}": {"label": f"node {i}"} for i in range(50)},
               "edges": [{"source": f"n{i}", "target": f"n{i+1}", "relation": "next"} for i in range(49)]}
    chunks = chunk_graph(graph_a, chunk_size=200)
    reconstructed = merge_graph({"nodes": {}, "edges": []}, chunks)
    assert reconstructed["nodes"] == graph_a["nodes"]
    assert reconstructed["edges"] == graph_a["edges"]

    graph_b = {"nodes": {f"n{i}": {"label": f"node {i} FROM PEER"} for i in range(40, 60)},
               "edges": [{"source": "n40", "target": "n41", "relation": "next"}]}  # overlaps + 1 dup edge
    merged = merge_graph(graph_a, chunk_graph(graph_b))
    assert len(merged["nodes"]) == 60          # 0..59, union
    assert merged["nodes"]["n45"]["label"] == "node 45 FROM PEER"  # incoming wins on conflict
    assert len(merged["edges"]) == 49           # the duplicate edge was NOT double-added
    print("[2/3] Chunk/merge round-trip + union-with-dedup: OK")

    # 3. Real TCP transfer over 127.0.0.1: one thread serves, this thread
    #    pulls, decrypts, and merges -- exercises the actual socket code,
    #    not just the pure logic above.
    import threading
    test_graph = {"nodes": {"a": {"label": "Alpha"}, "b": {"label": "Beta"}},
                  "edges": [{"source": "a", "target": "b", "relation": "connects_to"}]}
    port = 51909
    server_thread = threading.Thread(
        target=serve_graph_sync, args=(lambda: test_graph, "test-pass", "127.0.0.1", port, True),
        daemon=True)
    server_thread.start()
    time.sleep(0.3)
    pulled_chunks = pull_graph_from_peer("127.0.0.1", "test-pass", port=port, timeout=5)
    merged = merge_graph({"nodes": {}, "edges": []}, pulled_chunks)
    assert merged == test_graph, f"transferred graph didn't match: {merged}"
    print("[3/3] Real TCP transfer over 127.0.0.1 (encrypt -> send -> receive -> decrypt -> merge): OK")

    print("\nAll graph_sync self-tests passed.")


if __name__ == "__main__":
    _self_test()
