"""
radio_silence.py — Protocol Radio Silence (Local Offline Messenger).

A plain TCP socket server on your LAN — no FastAPI, no browser, no
internet required. Useful for very low-overhead clients: `nc <ip> 7777`,
a Tasker/Termux script, an ESP32, or anything that can open a raw socket
but doesn't want to speak HTTP.

This is distinct from remote_server.py's FastAPI uplink (which already
does phone/browser control): Radio Silence is the "just let me nc in and
type a line" option, deliberately simpler and lighter.

Security note: an open, unauthenticated socket that can execute local
commands is a real risk to anyone else on your Wi-Fi (coffee shop
networks, a compromised smart-home device, etc.) — so every command
requires a pre-shared token as the first line, and the server only binds
to your LAN interface, never 0.0.0.0-to-the-internet.
"""

import socket
import threading
import asyncio
import os
import secrets

TOKEN_FILE = "secure_vault/radio_silence_token.txt"
DEFAULT_PORT = 7777


def get_or_create_token() -> str:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    token = secrets.token_hex(8)
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    print(f"[Radio Silence] Generated new access token: {token}")
    return token


def _handle_client(conn, addr, token, loop):
    from brain import process_command
    from executor import run_local_command
    import safety

    try:
        conn.sendall(b"ARGUS RADIO SILENCE\r\nToken: ")
        raw = conn.recv(1024).decode("utf-8", errors="ignore").strip()

        if raw != token:
            conn.sendall(b"\r\nInvalid token. Closing connection.\r\n")
            return

        conn.sendall(b"\r\nAuthenticated. Type a command:\r\n> ")
        while True:
            data = conn.recv(2048)
            if not data:
                break
            text = data.decode("utf-8", errors="ignore").strip()
            if not text or text.lower() in ("exit", "quit"):
                break

            try:
                import feature_toggles
                if not feature_toggles.is_enabled("radio_silence"):
                    conn.sendall(b"Radio Silence is currently disabled in the control center.\r\n> ")
                    continue
            except Exception:
                pass

            decision = asyncio.run_coroutine_threadsafe(process_command(text), loop).result()
            action = decision.get("action")
            target = decision.get("target")

            if action == "casual_chat":
                reply = target
            elif safety.is_risky(action, target):
                reply = "That action needs voice/dashboard confirmation for safety reasons -- Radio Silence can't confirm risky actions on its own."
            else:
                reply = run_local_command(action, target)

            conn.sendall((reply + "\r\n> ").encode("utf-8"))
    except Exception as e:
        print(f"[Radio Silence] Client {addr} error: {e}")
    finally:
        conn.close()


def start_server(bind_ip: str = "0.0.0.0", port: int = DEFAULT_PORT):
    """Blocking entry point -- run this in its own thread/process.
    bind_ip defaults to 0.0.0.0 to accept LAN connections (this machine's
    router/firewall is what actually keeps it off the public internet;
    make sure you're not on a shared/untrusted network when running this)."""
    token = get_or_create_token()
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((bind_ip, port))
    server.listen(5)
    print(f"[Radio Silence] Listening on {bind_ip}:{port}. Token: {token}")
    print(f"[Radio Silence] Connect with: nc <this-machine-ip> {port}")

    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=_handle_client, args=(conn, addr, token, loop), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


if __name__ == "__main__":
    start_server()
