"""
gatekeeper.py — Protocol Gatekeeper (Local Multi-Factor Auth Router).

When a browser hits remote_server.py from an IP it hasn't seen before,
this generates a 6-digit OTP and requires it before issuing a session
cookie. Delivery is scoped honestly to what this project actually has
available for a single-user local tool:

  1. If email_agent.py is configured (SMTP env vars set), the code is
     emailed to you.
  2. Always: the code is also printed to the console running
     remote_server.py and, if any device is already connected via the
     /stream websocket (e.g. your phone from an earlier trusted session),
     broadcast there too.

There's no real SMS gateway wired up here -- that needs a paid third-party
API (Twilio etc.) with its own account/credentials, which isn't something
to fabricate. If you want true SMS delivery, wire your Twilio credentials
into a small extension of send_otp() below.
"""

import os
import json
import time
import random
import secrets

STATE_FILE = "secure_vault/gatekeeper_state.json"
OTP_VALIDITY_SECONDS = 300
SESSION_VALIDITY_SECONDS = 60 * 60 * 12  # 12 hours


def _load_state():
    if not os.path.exists(STATE_FILE):
        return {"known_ips": [], "pending_otps": {}, "sessions": {}}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"known_ips": [], "pending_otps": {}, "sessions": {}}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_known_ip(ip: str) -> bool:
    state = _load_state()
    return ip in state.get("known_ips", [])


def is_valid_session(session_token: str) -> bool:
    if not session_token:
        return False
    state = _load_state()
    session = state.get("sessions", {}).get(session_token)
    if not session:
        return False
    return (time.time() - session["created_at"]) < SESSION_VALIDITY_SECONDS


def generate_otp(ip: str) -> str:
    """Creates a fresh OTP for this IP and delivers it via every
    available channel. Returns the OTP only for local console logging --
    never send it back in the HTTP response, or the whole point is moot."""
    code = f"{random.randint(0, 999999):06d}"
    state = _load_state()
    state.setdefault("pending_otps", {})[ip] = {"code": code, "created_at": time.time()}
    _save_state(state)

    print(f"\n[Gatekeeper] New login attempt from {ip}. Verification code: {code}\n")

    try:
        import email_agent
        if email_agent.is_configured():
            email_agent.send_email(
                email_agent.SMTP_USER,
                "Argus Dashboard Login Code",
                f"A login attempt from IP {ip} needs this code to proceed: {code}\n"
                f"If this wasn't you, ignore this -- the code expires in 5 minutes."
            )
    except Exception as e:
        print(f"[Gatekeeper] Email delivery skipped/failed: {e}")

    return code


def broadcast_otp_via_websocket(ip: str, code: str, connected_clients):
    """Call this from remote_server.py right after generate_otp(), passing
    its connected_clients set, so any already-trusted device sees the code."""
    import asyncio
    payload = json.dumps({"type": "gatekeeper_otp", "ip": ip, "code": code})
    for client in list(connected_clients):
        try:
            asyncio.create_task(client.send_text(payload))
        except Exception:
            pass


def verify_otp(ip: str, submitted_code: str) -> str:
    """Returns a new session token on success, or None on failure/expiry."""
    state = _load_state()
    pending = state.get("pending_otps", {}).get(ip)
    if not pending:
        return None
    if (time.time() - pending["created_at"]) > OTP_VALIDITY_SECONDS:
        return None
    if submitted_code.strip() != pending["code"]:
        return None

    if ip not in state["known_ips"]:
        state["known_ips"].append(ip)
    del state["pending_otps"][ip]

    session_token = secrets.token_hex(24)
    state.setdefault("sessions", {})[session_token] = {"ip": ip, "created_at": time.time()}
    _save_state(state)
    return session_token
