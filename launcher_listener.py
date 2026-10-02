"""
launcher_listener.py — Protocol Wireless Launcher (phone-triggered start).

A phone can't "wirelessly start Argus" by talking to remote_server.py,
because if Argus isn't running yet, remote_server.py isn't listening
either -- there's nothing to connect to. This is the separate, tiny
piece that IS always listening: its only job is to accept a properly
authenticated start request, then launch launch.py.

WHY THIS IS ITS OWN SEPARATE SCRIPT: it has to be reachable precisely
when the rest of Argus is NOT running. It therefore imports NOTHING
heavy -- no ollama, torch, sentence_transformers, faiss. Just
fastapi/uvicorn (already project dependencies) and the stdlib. Run
this via Windows Task Scheduler at login (see SETUP.md) so it's live
whenever the laptop is on, independent of whether Argus itself is.

THE SECURITY DESIGN, IN ONE PARAGRAPH: the PIN never leaves the phone,
and this laptop never stores it or sees it. The phone's Argus Launcher
app (launcher_pwa/) encrypts the real password LOCALLY using a key
derived from the PIN via the Web Crypto API -- entering the wrong PIN
simply fails to decrypt anything, so no network request happens at
all on a wrong PIN. Once decrypted, the phone proves it holds the
correct password via an HMAC challenge-response (the /challenge and
/start endpoints below) -- the raw password itself is never sent over
the network, only proof that the phone's derived key matches what this
laptop derives from the SAME password (read from the
ARGUS_LAUNCHER_PASSWORD environment variable -- same "never in a
tracked file" pattern as ARGUS_GRAPH_SYNC_PASSPHRASE in graph_sync.py).
See _verify_proof() for exactly what travels and why nothing secret
has to, either direction, to do it. The PBKDF2 salt below is fixed and
non-secret -- see graph_sync.py's identical reasoning: both sides need
to derive the same key from the same password with no prior exchange,
so the salt can't be randomly chosen per device.

The Python side of this file's crypto (PBKDF2-HMAC-SHA256, then
HMAC-SHA256 over the nonce) was verified byte-for-byte identical
against Node's `crypto` module (which uses the same primitives the
browser's Web Crypto API does) before this was written -- same
password, same salt, same iteration count in, same derived key and
signature out on both sides.
"""

import hashlib
import hmac
import os
import secrets
import subprocess
import sys
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
import uvicorn

import audit
import feature_toggles

LAUNCHER_SALT = b"argus-launcher-fixed-salt-v1"   # not secret -- see module docstring
PBKDF2_ITERATIONS = 200_000                        # MUST match the PWA's client-side PBKDF2 call exactly
NONCE_TTL_SECONDS = 90
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300
LISTENER_PORT = 8765
PID_FILE = "argus_supervisor.pid"

app = FastAPI(title="Argus Remote Launcher")

_PWA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher_pwa")

_pending_nonces = {}       # nonce -> expiry timestamp
_failed_attempts = {}      # ip -> [timestamp, ...]


# ---------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------

def _derive_key(password: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), LAUNCHER_SALT, PBKDF2_ITERATIONS, dklen=32)


def _verify_proof(nonce: str, proof_hex: str) -> bool:
    """The phone derives HMAC-SHA256(PBKDF2(password), nonce) locally
    and sends the result as `proof`. This laptop derives the SAME key
    from its own copy of the password (the env var) and recomputes the
    same HMAC to compare. Neither side ever transmits the password OR
    the derived key -- only an HMAC over a single-use nonce, useless to
    replay and revealing nothing about the secret it came from."""
    password = os.environ.get("ARGUS_LAUNCHER_PASSWORD")
    if not password:
        return False
    key = _derive_key(password)
    expected = hmac.new(key, nonce.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, proof_hex)


# ---------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------

def _client_locked_out(ip: str) -> bool:
    cutoff = time.time() - LOCKOUT_SECONDS
    recent = [t for t in _failed_attempts.get(ip, []) if t > cutoff]
    _failed_attempts[ip] = recent
    return len(recent) >= MAX_FAILED_ATTEMPTS


def _record_failure(ip: str):
    _failed_attempts.setdefault(ip, []).append(time.time())


def _record_success(ip: str):
    _failed_attempts.pop(ip, None)


# ---------------------------------------------------------------------
# Starting Argus
# ---------------------------------------------------------------------

def _already_running() -> bool:
    """Best-effort check via a PID file this function itself writes/
    reads -- not a claim about remote_server.py's actual port state,
    just enough to stop an accidental double-tap from spawning a
    second supervisor on top of one already starting."""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        if sys.platform == "win32":
            result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
            return str(pid) in result.stdout
        os.kill(pid, 0)  # signal 0: existence check only, doesn't actually signal the process
        return True
    except (OSError, ValueError):
        return False


def _launch_argus() -> int:
    project_dir = os.path.dirname(os.path.abspath(__file__))
    popen_kwargs = {"cwd": project_dir}
    if sys.platform == "win32":
        # Fully detach from this listener's process group -- if the
        # listener itself later restarts or is stopped, the Argus
        # supervisor it just started must keep running independently.
        popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen([sys.executable, "launch.py", "--mode", "remote"], **popen_kwargs)
    with open(PID_FILE, "w") as f:
        f.write(str(process.pid))
    return process.pid


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------

@app.get("/challenge")
async def get_challenge():
    nonce = secrets.token_hex(16)
    _pending_nonces[nonce] = time.time() + NONCE_TTL_SECONDS
    cutoff = time.time()
    for stale in [n for n, expiry in _pending_nonces.items() if expiry < cutoff]:
        _pending_nonces.pop(stale, None)
    return {"nonce": nonce, "iterations": PBKDF2_ITERATIONS, "ttl_seconds": NONCE_TTL_SECONDS}


@app.post("/start")
async def start_argus(request: Request):
    ip = request.client.host if request.client else "unknown"

    if _client_locked_out(ip):
        return JSONResponse({"error": "Too many failed attempts. Try again in a few minutes."}, status_code=429)

    # Fail CLOSED on an unreadable toggle, deliberately the opposite of
    # executor.py's _feature_on() -- that helper fails open because a
    # broken toggle file shouldn't block an ordinary chat action; THIS
    # endpoint launches a process, so an unreadable toggle file should
    # not silently allow that instead.
    try:
        enabled = feature_toggles.is_enabled("remote_launcher")
    except Exception:
        enabled = False
    if not enabled:
        return JSONResponse({"error": "Protocol Remote Launch is toggled off."}, status_code=403)

    body = await request.json()
    nonce = body.get("nonce", "")
    proof = body.get("proof", "")

    expiry = _pending_nonces.pop(nonce, None)  # pop: single-use regardless of outcome
    if expiry is None or time.time() > expiry:
        _record_failure(ip)
        audit.log_action("remote_launch", ip, "rejected: expired/unknown nonce")
        return JSONResponse({"error": "Challenge expired or invalid. Request a new one from /challenge."}, status_code=401)

    if not _verify_proof(nonce, proof):
        _record_failure(ip)
        audit.log_action("remote_launch", ip, "rejected: password proof mismatch")
        return JSONResponse({"error": "Authentication failed."}, status_code=401)

    _record_success(ip)
    audit.log_action("remote_launch", ip, "accepted")
    print(f"[Remote Launch] Verified request from {ip} -- launching Argus.")

    if _already_running():
        print("[Remote Launch] Argus (or a previous launch) already appears to be running -- not starting a second one.")
        return {"status": "already_running"}

    pid = _launch_argus()
    print(f"[Remote Launch] Started launch.py --mode remote (pid {pid}).")
    return {"status": "started", "pid": pid}


@app.get("/status")
async def status():
    """Lets the phone check 'is the listener even reachable' before
    walking through a PIN entry -- no auth needed, reveals nothing
    sensitive (not even whether Argus itself is currently running)."""
    return {"listener": "up"}


# ---------------- Serving the PWA itself ----------------
# Has to be served by THIS listener, not remote_server.py -- the whole
# point of the launcher app is reaching it while Argus (and therefore
# remote_server.py) isn't running at all. Explicit routes rather than
# a blanket StaticFiles mount at "/", so the API endpoints above stay
# unambiguous.

@app.get("/")
async def serve_pwa_index():
    return FileResponse(os.path.join(_PWA_DIR, "index.html"), headers={"Cache-Control": "no-store"})


@app.get("/manifest.json")
async def serve_pwa_manifest():
    return FileResponse(os.path.join(_PWA_DIR, "manifest.json"), media_type="application/manifest+json")


@app.get("/service-worker.js")
async def serve_pwa_service_worker():
    return FileResponse(
        os.path.join(_PWA_DIR, "service-worker.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/icon.svg")
async def serve_pwa_icon():
    return FileResponse(os.path.join(_PWA_DIR, "icon.svg"), media_type="image/svg+xml")


if __name__ == "__main__":
    if not os.environ.get("ARGUS_LAUNCHER_PASSWORD"):
        print("[Remote Launch] ARGUS_LAUNCHER_PASSWORD isn't set in this shell -- every /start request will fail.")
        print("  Windows:  setx ARGUS_LAUNCHER_PASSWORD \"your-password-here\"   (then open a NEW terminal)")
        print("  Linux/macOS: export ARGUS_LAUNCHER_PASSWORD=\"your-password-here\"")
    print(f"[Remote Launch] Listening on 0.0.0.0:{LISTENER_PORT}.")
    uvicorn.run(app, host="0.0.0.0", port=LISTENER_PORT)
