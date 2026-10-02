import os
import json
import asyncio
import io
import shutil
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
import uvicorn
from pydub import AudioSegment
import soundfile as sf
from PIL import ImageGrab
import pyautogui

import database
import brain
from brain import process_command
from executor import run_local_command
from voice_engine import whisper_model, tts_model, transcribe_audio, generate_speech_base64
import ollama
import safety
import agent_orchestrator
import notifier
import feature_toggles
import model_router
import self_dev
import audit
import document_processor
import mirage_cam
import gatekeeper
import castellan

app = FastAPI(title="Argus Secure Comms")
os.makedirs("audio_cache", exist_ok=True)

# Feature 5: proactive notifications. Every open /stream websocket is
# tracked here so background watchdogs (overwatch, aegis, security_warden)
# can push alerts to whoever's currently connected.
connected_clients = set()
_alert_file_offset = 0

async def alert_broadcaster():
    """Background task: polls notifier.py's shared alert file and pushes
    any new entries out to every connected websocket client."""
    global _alert_file_offset
    while True:
        try:
            alerts, _alert_file_offset = notifier.drain_new_alerts(_alert_file_offset)
            for alert in alerts:
                payload = json.dumps({
                    "type": "notification",
                    "source": alert.get("source"),
                    "text": alert.get("message"),
                    "level": alert.get("level", "info"),
                })
                stale_clients = []
                for client in connected_clients:
                    try:
                        await client.send_text(payload)
                    except Exception:
                        stale_clients.append(client)
                for client in stale_clients:
                    connected_clients.discard(client)
        except Exception as e:
            print(f"[Alert Broadcaster Error]: {e}")
        await asyncio.sleep(2)

async def self_dev_background_loop():
    """Runs the Self-Development Engine's diagnosis cycle periodically
    from inside remote_server.py too, so it still works even if you're
    not running it via launch.py's self_dev_daemon.py. Skips entirely
    (cheaply) when the "self_dev_engine" toggle is off."""
    while True:
        await asyncio.sleep(60 * 20)
        try:
            await asyncio.to_thread(self_dev.run_cycle)
        except Exception as e:
            print(f"[Self-Dev Background Loop Error]: {e}")

@app.on_event("startup")
async def on_startup():
    await database.init_db()
    asyncio.create_task(alert_broadcaster())
    asyncio.create_task(self_dev_background_loop())

# ---------------- Protocol Gatekeeper: local MFA gate ----------------
# Any route not in this allowlist requires a verified session once
# "gatekeeper_mfa" is toggled on. Verification issues a signed-ish
# session token (see gatekeeper.py) stored in a cookie.
_GATEKEEPER_ALLOWLIST = {"/verify", "/verify_submit", "/favicon.ico"}

@app.middleware("http")
async def gatekeeper_mfa_middleware(request: Request, call_next):
    if not feature_toggles.is_enabled("gatekeeper_mfa"):
        return await call_next(request)
    if request.url.path in _GATEKEEPER_ALLOWLIST:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    session_token = request.cookies.get("argus_session")

    if gatekeeper.is_valid_session(session_token) or gatekeeper.is_known_ip(client_ip):
        return await call_next(request)

    # New/unverified IP: send them to /verify instead of serving the request.
    code = gatekeeper.generate_otp(client_ip)
    gatekeeper.broadcast_otp_via_websocket(client_ip, code, connected_clients)
    return RedirectResponse(url=f"/verify?ip={client_ip}")

@app.get("/verify", response_class=HTMLResponse)
async def verify_page(ip: str = ""):
    return f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8"><title>Argus — Verify</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ background:#0A0E14; color:#E8EDF5; font-family:'IBM Plex Sans',-apple-system,sans-serif; display:flex; align-items:center; justify-content:center; height:100vh; margin:0; }}
        .card {{ background:#12161F; border:1px solid #232B3D; border-radius:14px; padding:32px; width:90%; max-width:340px; text-align:center; }}
        h1 {{ font-size:1.1em; color:#3DDC84; margin-bottom:6px; }}
        p {{ color:#6B7686; font-size:0.85em; margin-top:0; }}
        input {{ width:100%; box-sizing:border-box; background:#0A0E14; border:1px solid #232B3D; color:#E8EDF5; padding:14px; border-radius:8px; font-size:1.3em; text-align:center; letter-spacing:6px; margin:16px 0; }}
        button {{ width:100%; padding:14px; border:none; border-radius:8px; background:#3DDC84; color:#0A0E14; font-weight:600; cursor:pointer; }}
        #err {{ color:#FF5C7A; font-size:0.85em; min-height:1.2em; }}
    </style></head>
    <body>
        <div class="card">
            <h1>🔒 Protocol Gatekeeper</h1>
            <p>New device detected. Enter the code shown on your Argus console.</p>
            <input id="code" maxlength="6" inputmode="numeric" placeholder="000000" autofocus>
            <div id="err"></div>
            <button onclick="submitCode()">Verify</button>
        </div>
        <script>
            async function submitCode() {{
                const code = document.getElementById('code').value;
                const res = await fetch('/verify_submit', {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{ip: "{ip}", code: code}})
                }});
                const data = await res.json();
                if (data.success) {{ window.location.href = "/"; }}
                else {{ document.getElementById('err').innerText = "Incorrect or expired code."; }}
            }}
        </script>
    </body></html>
    """

@app.post("/verify_submit")
async def verify_submit(request: Request, response: Response):
    body = await request.json()
    ip = body.get("ip", "")
    code = body.get("code", "")
    session_token = gatekeeper.verify_otp(ip, code)
    if not session_token:
        return {"success": False}
    resp = Response(content=json.dumps({"success": True}), media_type="application/json")
    resp.set_cookie("argus_session", session_token, max_age=gatekeeper.SESSION_VALIDITY_SECONDS, httponly=True)
    return resp

@app.get("/", response_class=HTMLResponse)
async def get_ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Argus // Console</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
        <style>
            :root {
                --void: #0A0E14;
                --panel: #12161F;
                --panel-2: #161B26;
                --border: #232B3D;
                --border-soft: #1A2030;
                --iris: #3DDC84;
                --iris-dim: #1E6B44;
                --signal-blue: #4FA8FF;
                --signal-violet: #A277FF;
                --signal-amber: #FFB454;
                --signal-red: #FF5C7A;
                --text: #E8EDF5;
                --text-dim: #8892A6;
                --text-faint: #4B5468;
                --font-display: 'IBM Plex Mono', monospace;
                --font-body: 'IBM Plex Sans', -apple-system, sans-serif;
            }
            * { box-sizing: border-box; }
            body {
                font-family: var(--font-body);
                background: var(--void);
                background-image:
                    radial-gradient(ellipse 80% 50% at 50% -10%, rgba(61,220,132,0.06), transparent),
                    radial-gradient(ellipse 60% 40% at 100% 100%, rgba(162,119,255,0.05), transparent);
                color: var(--text);
                margin: 0;
                min-height: 100vh;
            }
            ::selection { background: var(--iris-dim); color: var(--text); }
            ::-webkit-scrollbar { width: 8px; height: 8px; }
            ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
            a { color: var(--signal-blue); }

            /* ---------- Header / Iris ---------- */
            header {
                display: flex; align-items: center; justify-content: space-between;
                padding: 14px 20px; border-bottom: 1px solid var(--border-soft);
                position: sticky; top: 0; background: rgba(10,14,20,0.9); backdrop-filter: blur(10px);
                z-index: 50; gap: 12px; flex-wrap: wrap;
            }
            .brand { display: flex; align-items: center; gap: 12px; }
            .brand-name {
                font-family: var(--font-display); font-weight: 600; font-size: 1.05em;
                letter-spacing: 0.12em; color: var(--text);
            }
            .brand-name span { color: var(--iris); }
            .header-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

            #iris-svg { width: 36px; height: 36px; display: block; }
            #iris-svg .iris-ring { transition: all 0.6s cubic-bezier(.4,0,.2,1); transform-origin: center; }
            #iris-svg .iris-pupil { transition: all 0.6s cubic-bezier(.4,0,.2,1); transform-origin: center; }
            .status-idle #iris-svg .iris-ring { animation: breathe 4s ease-in-out infinite; }
            .status-listening #iris-svg .iris-ring { stroke: var(--signal-blue); animation: dilate 1.2s ease-in-out infinite; }
            .status-listening #iris-svg .iris-pupil { fill: var(--signal-blue); r: 9; }
            .status-thinking #iris-svg .iris-ring { stroke: var(--signal-violet); animation: spin 1.6s linear infinite; }
            .status-danger #iris-svg .iris-pupil { ry: 2; fill: var(--signal-red); }
            .status-danger #iris-svg .iris-ring { stroke: var(--signal-red); }
            @keyframes breathe { 0%,100% { opacity: 0.55; } 50% { opacity: 1; } }
            @keyframes dilate { 0%,100% { transform: scale(1); } 50% { transform: scale(1.18); } }
            @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

            /* ---------- Pills / buttons ---------- */
            .pill-select {
                background: var(--panel); border: 1px solid var(--border); color: var(--text);
                font-family: var(--font-display); font-size: 0.78em; padding: 8px 12px; border-radius: 20px;
                cursor: pointer; display: flex; align-items: center; gap: 6px;
            }
            select.pill-select { appearance: none; -webkit-appearance: none; padding-right: 28px;
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%238892A6'/%3E%3C/svg%3E");
                background-repeat: no-repeat; background-position: right 10px center;
            }
            .icon-btn {
                background: var(--panel); border: 1px solid var(--border); color: var(--text-dim);
                width: 38px; height: 38px; border-radius: 10px; cursor: pointer; display: flex;
                align-items: center; justify-content: center; font-size: 1.05em; position: relative;
                transition: 0.15s;
            }
            .icon-btn:hover { color: var(--text); border-color: var(--iris-dim); }
            .icon-btn .dot { position: absolute; top: -3px; right: -3px; width: 9px; height: 9px; border-radius: 50%; background: var(--signal-amber); display: none; }
            .icon-btn .dot.show { display: block; }

            /* ---------- Layout ---------- */
            .layout { display: grid; grid-template-columns: 300px 1fr; gap: 16px; padding: 16px 20px 40px; max-width: 1400px; margin: 0 auto; }
            @media (max-width: 880px) { .layout { grid-template-columns: 1fr; } #protocol-rail { display: none; } #protocol-rail.open { display: block; } }

            /* ---------- Protocol rail ---------- */
            #protocol-rail { display: flex; flex-direction: column; gap: 14px; }
            .rail-header { font-family: var(--font-display); font-size: 0.7em; letter-spacing: 0.14em; color: var(--text-faint); text-transform: uppercase; padding: 0 4px; }
            .category-block { background: var(--panel); border: 1px solid var(--border-soft); border-radius: 12px; overflow: hidden; }
            .category-title {
                display: flex; justify-content: space-between; align-items: center; padding: 11px 14px;
                font-family: var(--font-display); font-size: 0.72em; letter-spacing: 0.08em; color: var(--text-dim);
                text-transform: uppercase; border-bottom: 1px solid var(--border-soft); cursor: pointer;
            }
            .category-count { color: var(--iris); font-weight: 600; }
            .protocol-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; gap: 10px; border-bottom: 1px solid var(--border-soft); }
            .protocol-row:last-child { border-bottom: none; }
            .protocol-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
            .protocol-name { font-size: 0.85em; color: var(--text); }
            .protocol-desc { font-size: 0.72em; color: var(--text-faint); line-height: 1.3; }

            /* Toggle switch */
            .switch { position: relative; width: 38px; height: 21px; flex-shrink: 0; }
            .switch input { opacity: 0; width: 0; height: 0; }
            .switch .track { position: absolute; inset: 0; background: var(--border); border-radius: 20px; cursor: pointer; transition: 0.2s; }
            .switch .track:before { content: ""; position: absolute; width: 15px; height: 15px; left: 3px; top: 3px; background: var(--text-faint); border-radius: 50%; transition: 0.2s; }
            .switch input:checked + .track { background: var(--iris-dim); }
            .switch input:checked + .track:before { transform: translateX(17px); background: var(--iris); }

            /* ---------- Main console ---------- */
            #console { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
            .panel { background: var(--panel); border: 1px solid var(--border-soft); border-radius: 14px; padding: 16px; }
            #monitor-feed { width: 100%; border-radius: 10px; display: none; border: 1px solid var(--border); margin-bottom: 12px; }
            #chat-feed { background: var(--void); padding: 16px; border-radius: 10px; height: 340px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
            .msg-user, .msg-argus { max-width: 78%; padding: 10px 13px; border-radius: 13px; font-size: 0.9em; line-height: 1.4; }
            .msg-user { color: var(--void); align-self: flex-end; background: var(--iris); border-radius: 13px 13px 3px 13px; font-weight: 500; }
            .msg-argus { color: var(--text); align-self: flex-start; background: var(--panel-2); border: 1px solid var(--border-soft); border-radius: 13px 13px 13px 3px; }
            .status-line { text-align: center; font-family: var(--font-display); font-size: 0.72em; color: var(--text-faint); padding: 10px 0 2px; letter-spacing: 0.04em; }

            .input-row { display: flex; gap: 8px; margin-top: 12px; }
            #cmdInput { flex: 1; background: var(--void); border: 1px solid var(--border); color: var(--text); padding: 13px 14px; border-radius: 10px; font-family: var(--font-body); font-size: 0.92em; }
            #cmdInput:focus { outline: none; border-color: var(--iris-dim); }
            .btn { padding: 13px 18px; border-radius: 10px; font-weight: 600; border: none; cursor: pointer; font-size: 0.85em; transition: 0.15s; font-family: var(--font-body); white-space: nowrap; }
            .btn-primary { background: var(--iris); color: var(--void); }
            .btn-primary:hover { filter: brightness(1.1); }
            .action-row { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
            .btn-ghost { background: transparent; border: 1px solid var(--border); color: var(--text-dim); flex: 1; min-width: 120px; }
            .btn-ghost:hover { border-color: var(--signal-blue); color: var(--text); }
            .btn-ghost.active-call { border-color: var(--signal-red); color: var(--signal-red); animation: pulse-border 1.6s infinite; }
            .btn-ghost.active-rec { border-color: var(--signal-red); color: var(--signal-red); }
            .btn-ghost.active-view { border-color: var(--signal-violet); color: var(--signal-violet); }
            @keyframes pulse-border { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }

            /* ---------- Confirmation banner ---------- */
            #confirm-banner { display: none; background: rgba(255,92,122,0.08); border: 1px solid var(--signal-red); border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; font-size: 0.85em; }
            #confirm-banner .confirm-actions { display: flex; gap: 8px; margin-top: 10px; }
            #confirm-banner button { flex: 1; padding: 8px; border-radius: 7px; border: none; cursor: pointer; font-weight: 600; font-size: 0.85em; }
            .btn-confirm-yes { background: var(--signal-red); color: white; }
            .btn-confirm-no { background: var(--border); color: var(--text); }

            /* ---------- Drawer (Log History) ---------- */
            #drawer-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 90; }
            #drawer { position: fixed; top: 0; right: -420px; width: 400px; max-width: 92vw; height: 100vh; background: var(--panel); border-left: 1px solid var(--border); z-index: 91; transition: right 0.25s ease; display: flex; flex-direction: column; }
            #drawer.open { right: 0; }
            #drawer-overlay.open { display: block; }
            .drawer-head { padding: 16px 18px; border-bottom: 1px solid var(--border-soft); display: flex; justify-content: space-between; align-items: center; }
            .drawer-head h2 { margin: 0; font-family: var(--font-display); font-size: 0.95em; letter-spacing: 0.06em; }
            .drawer-tabs { display: flex; gap: 4px; padding: 10px 18px 0; border-bottom: 1px solid var(--border-soft); }
            .drawer-tab { padding: 8px 12px; font-size: 0.78em; color: var(--text-faint); cursor: pointer; border-bottom: 2px solid transparent; font-family: var(--font-display); }
            .drawer-tab.active { color: var(--iris); border-bottom-color: var(--iris); }
            .drawer-body { flex: 1; overflow-y: auto; padding: 14px 18px; display: flex; flex-direction: column; gap: 10px; }
            .log-entry { background: var(--void); border: 1px solid var(--border-soft); border-radius: 10px; padding: 11px 13px; font-size: 0.8em; }
            .log-entry .log-meta { color: var(--text-faint); font-family: var(--font-display); font-size: 0.75em; margin-bottom: 4px; display: flex; justify-content: space-between; }
            .log-badge { padding: 2px 7px; border-radius: 5px; font-size: 0.72em; font-family: var(--font-display); }
            .badge-pending { background: rgba(255,180,84,0.15); color: var(--signal-amber); }
            .badge-approved { background: rgba(61,220,132,0.15); color: var(--iris); }
            .badge-rejected { background: rgba(255,92,122,0.15); color: var(--signal-red); }
            .badge-info { background: rgba(79,168,255,0.15); color: var(--signal-blue); }
            .log-diff { background: #0A0E14; border-radius: 6px; padding: 8px; font-family: var(--font-display); font-size: 0.72em; white-space: pre-wrap; max-height: 140px; overflow-y: auto; margin-top: 6px; color: var(--text-dim); }
            .log-actions { display: flex; gap: 6px; margin-top: 8px; }
            .log-actions button { flex: 1; padding: 7px; border-radius: 6px; border: none; font-size: 0.78em; cursor: pointer; font-weight: 600; }
            .btn-approve { background: var(--iris); color: var(--void); }
            .btn-reject { background: transparent; border: 1px solid var(--border) !important; color: var(--text-dim); }
            .empty-note { color: var(--text-faint); font-size: 0.82em; text-align: center; padding: 30px 10px; }

            /* Toast notifications */
            #toast-stack { position: fixed; bottom: 16px; right: 16px; z-index: 99; display: flex; flex-direction: column; gap: 8px; }
            .toast { background: var(--panel); border: 1px solid var(--border); border-left: 3px solid var(--signal-blue); border-radius: 8px; padding: 10px 14px; font-size: 0.8em; max-width: 300px; animation: slidein 0.2s ease; }
            .toast.warning { border-left-color: var(--signal-amber); }
            .toast.critical { border-left-color: var(--signal-red); }
            @keyframes slidein { from { transform: translateX(20px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

            /* Protocol Remote Cursor Control: fullscreen screen view */
            #fs-overlay {
                position: fixed; inset: 0; background: #000; z-index: 999;
                display: none; flex-direction: column;
            }
            #fs-overlay.active { display: flex; }
            #fs-topbar {
                display: flex; justify-content: space-between; align-items: center;
                padding: 10px 14px; background: var(--panel); border-bottom: 1px solid var(--border);
                flex-shrink: 0;
            }
            #fs-hint { font-family: var(--font-display); font-size: 0.72em; color: var(--text-dim); }
            #fs-close {
                background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
                padding: 7px 14px; border-radius: 6px; font-family: var(--font-display); font-size: 0.75em;
                cursor: pointer;
            }
            #fs-screen-wrap {
                flex: 1; position: relative; display: flex; align-items: center; justify-content: center;
                touch-action: none; overflow: hidden; background: #000;
            }
            #fs-screen-img { max-width: 100%; max-height: 100%; object-fit: contain; user-select: none; -webkit-user-drag: none; }
            #fs-cursor {
                position: absolute; width: 26px; height: 26px; pointer-events: none;
                transform: translate(-3px, -3px); display: none;
                filter: drop-shadow(0 1px 4px rgba(0,0,0,0.9));
            }
            #fs-cursor.active { display: block; }
            #fs-cursor-dot {
                position: absolute; width: 10px; height: 10px; border-radius: 50%;
                background: var(--signal-blue); border: 2px solid var(--text);
                transform: translate(-5px, -5px);
            }
            #fs-status {
                position: absolute; bottom: 14px; left: 50%; transform: translateX(-50%);
                background: rgba(18,22,31,0.85); border: 1px solid var(--border); border-radius: 20px;
                padding: 6px 14px; font-family: var(--font-display); font-size: 0.7em; color: var(--text-dim);
            }
        </style>
    </head>
    <body class="status-idle" id="body-root">

        <div id="fs-overlay">
            <div id="fs-topbar">
                <span id="fs-hint">drag to move the cursor &middot; tap to click &middot; two-finger tap to right-click</span>
                <button id="fs-close" onclick="closeFullscreenScreen()">&#10005; Exit</button>
            </div>
            <div id="fs-screen-wrap">
                <img id="fs-screen-img" src="" alt="Laptop screen" draggable="false">
                <div id="fs-cursor"><div id="fs-cursor-dot"></div></div>
                <div id="fs-status">connecting…</div>
            </div>
        </div>

        <header>
            <div class="brand">
                <svg id="iris-svg" viewBox="0 0 40 40">
                    <circle class="iris-ring" cx="20" cy="20" r="16" fill="none" stroke="#3DDC84" stroke-width="2" stroke-dasharray="3 4"/>
                    <circle cx="20" cy="20" r="11" fill="none" stroke="#232B3D" stroke-width="1"/>
                    <ellipse class="iris-pupil" cx="20" cy="20" rx="5" ry="5" fill="#3DDC84"/>
                </svg>
                <div class="brand-name">ARGUS<span>//</span>CONSOLE</div>
            </div>
            <div class="header-controls">
                <label class="pill-select" style="cursor:default;">
                    <input type="checkbox" id="autoRouteToggle" style="margin:0;" onchange="onAutoRouteChange()"> Auto-route
                </label>
                <select id="modelSelect" class="pill-select" onchange="onModelChange()"></select>
                <button class="icon-btn" title="Protocols" onclick="toggleRail()">&#9881;</button>
                <button class="icon-btn" title="Log History" onclick="openDrawer()">
                    &#128220;<span class="dot" id="pendingDot"></span>
                </button>
            </div>
        </header>

        <div class="layout">
            <aside id="protocol-rail">
                <div class="rail-header">Protocols // <span id="activeCount">0</span> active</div>
                <div id="categoryContainer"></div>
            </aside>

            <main id="console">
                <div class="panel">
                    <img id="monitor-feed" src="" alt="Live feed">
                    <div id="confirm-banner">
                        <div id="confirm-text"></div>
                        <div class="confirm-actions">
                            <button class="btn-confirm-yes" onclick="sendConfirm(true)">Confirm</button>
                            <button class="btn-confirm-no" onclick="sendConfirm(false)">Cancel</button>
                        </div>
                    </div>
                    <div id="chat-feed">
                        <div class="msg-argus">Argus is online. All systems nominal.</div>
                    </div>
                    <div class="status-line" id="status-text">SYSTEM IDLE</div>

                    <div class="input-row">
                        <input type="text" id="cmdInput" placeholder="Type a command or ask anything..." onkeydown="if(event.key==='Enter')transmitText()">
                        <button class="btn btn-primary" onclick="transmitText()">Send</button>
                    </div>
                    <div class="action-row">
                        <button id="voiceBtn" class="btn btn-ghost" onclick="toggleVoiceMessage()">🎙 Voice Message</button>
                        <button id="callBtn" class="btn btn-ghost" onclick="toggleCallMode()">📞 Live Call</button>
                        <button id="screenBtn" class="btn btn-ghost" onclick="toggleFeed('screen')">🖥 Screen</button>
                        <button id="camBtn" class="btn btn-ghost" onclick="toggleFeed('camera')">📷 Mirage Cam</button>
                    </div>
                </div>
            </main>
        </div>

        <div id="drawer-overlay" onclick="closeDrawer()"></div>
        <div id="drawer">
            <div class="drawer-head">
                <h2>Log History</h2>
                <button class="icon-btn" onclick="closeDrawer()">&times;</button>
            </div>
            <div class="drawer-tabs">
                <div class="drawer-tab active" id="tab-dev" onclick="switchDrawerTab('dev')">Self-Dev</div>
                <div class="drawer-tab" id="tab-audit" onclick="switchDrawerTab('audit')">Audit Trail</div>
            </div>
            <div class="drawer-body" id="drawerBody"></div>
        </div>

        <div id="toast-stack"></div>

        <script>
        // ---------- State ----------
let mediaRecorder, audioChunks = [], isRecording = false, isCallMode = false;
let activeFeed = null; // 'screen' | 'camera' | null
let ws, audioQueue = [], isPlaying = false;
let allFeatures = [];
let drawerTab = 'dev';

const statusText = document.getElementById('status-text');
const chatFeed = document.getElementById('chat-feed');
const monitorFeed = document.getElementById('monitor-feed');
const bodyRoot = document.getElementById('body-root');

function setIrisStatus(status) {
    bodyRoot.className = 'status-' + status;
}

function appendMessage(sender, text) {
    const msgDiv = document.createElement('div');
    msgDiv.className = sender === "User" ? "msg-user" : "msg-argus";
    msgDiv.textContent = text;
    chatFeed.appendChild(msgDiv);
    chatFeed.scrollTop = chatFeed.scrollHeight;
}

function showToast(text, level) {
    const stack = document.getElementById('toast-stack');
    const toast = document.createElement('div');
    toast.className = 'toast ' + (level || '');
    toast.textContent = text;
    stack.appendChild(toast);
    setTimeout(() => toast.remove(), 6000);
}

function playAudioResponse(base64Audio) {
    if (!base64Audio) return;
    const audio = new Audio("data:audio/wav;base64," + base64Audio);
    audio.play();
}

// ---------- Feed toggles (screen / camera) ----------
function toggleFeed(kind) {
    const screenBtn = document.getElementById('screenBtn');
    const camBtn = document.getElementById('camBtn');

    if (kind === 'screen') {
        // Screen feed now opens fullscreen with cursor control, rather
        // than the small inline monitor-feed camera uses -- watching a
        // compressed 800x600 thumbnail in a corner isn't usable for
        // actually driving the laptop.
        openFullscreenScreen();
        return;
    }

    if (activeFeed === kind) {
        monitorFeed.src = ""; monitorFeed.style.display = "none";
        activeFeed = null;
        screenBtn.classList.remove('active-view'); camBtn.classList.remove('active-view');
        return;
    }
    monitorFeed.src = "/camera_feed";
    monitorFeed.style.display = "block";
    activeFeed = kind;
    screenBtn.classList.toggle('active-view', kind === 'screen');
    camBtn.classList.toggle('active-view', kind === 'camera');
}

// ---------- Protocol Remote Cursor Control ----------
let cursorSocket = null;
let fsImgRect = null;
let lastCursorSend = 0;
const CURSOR_SEND_INTERVAL_MS = 45;   // ~22 updates/sec -- smooth without flooding the websocket
const TAP_MAX_MS = 400;
const TAP_MAX_MOVE_PX = 8;
let touchStartTime = 0, touchStartClientPos = null, touchMoved = false, touchFingerCount = 1;

function openFullscreenScreen() {
    const overlay = document.getElementById('fs-overlay');
    const img = document.getElementById('fs-screen-img');
    const status = document.getElementById('fs-status');
    img.src = "/screen_feed?t=" + Date.now();  // cache-bust so a fresh MJPEG stream opens every time
    overlay.classList.add('active');
    document.getElementById('fs-cursor').classList.remove('active');
    connectCursorSocket(status);
}

function closeFullscreenScreen() {
    document.getElementById('fs-overlay').classList.remove('active');
    document.getElementById('fs-screen-img').src = "";
    document.getElementById('screenBtn').classList.remove('active-view');
    if (cursorSocket) { cursorSocket.close(); cursorSocket = null; }
    fsImgRect = null;
}

function connectCursorSocket(statusEl) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    cursorSocket = new WebSocket(proto + '://' + location.host + '/ws/cursor');
    cursorSocket.onopen = () => { statusEl.textContent = 'cursor control connected'; };
    cursorSocket.onclose = (e) => {
        statusEl.textContent = e.code === 4403
            ? 'view-only \u2014 enable Protocol Remote Cursor Control to drag the cursor'
            : 'cursor control disconnected';
    };
    cursorSocket.onerror = () => { statusEl.textContent = 'cursor control unavailable'; };
}

// Computes the ACTUAL rendered bounds of the (object-fit: contain)
// image within its wrapper -- needed because the wrapper and the
// laptop's screen aspect ratio rarely match exactly, so the image is
// letterboxed. Touch coordinates have to be mapped against the real
// image bounds, not the wrapper's, or dragging near the letterboxed
// edges would map to the wrong point on the laptop screen.
function computeImageRect() {
    const img = document.getElementById('fs-screen-img');
    const wrap = document.getElementById('fs-screen-wrap');
    const wrapRect = wrap.getBoundingClientRect();
    const imgAspect = (img.naturalWidth && img.naturalHeight) ? (img.naturalWidth / img.naturalHeight) : (4 / 3);
    const wrapAspect = wrapRect.width / wrapRect.height;
    let w, h, top, left;
    if (imgAspect > wrapAspect) {
        w = wrapRect.width; h = w / imgAspect;
        left = wrapRect.left; top = wrapRect.top + (wrapRect.height - h) / 2;
    } else {
        h = wrapRect.height; w = h * imgAspect;
        top = wrapRect.top; left = wrapRect.left + (wrapRect.width - w) / 2;
    }
    return { left: left, top: top, width: w, height: h };
}

function clientPosToNormalized(clientX, clientY) {
    if (!fsImgRect) fsImgRect = computeImageRect();
    const x = (clientX - fsImgRect.left) / fsImgRect.width;
    const y = (clientY - fsImgRect.top) / fsImgRect.height;
    return { x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) };
}

function moveCursorOverlay(clientX, clientY) {
    const cursor = document.getElementById('fs-cursor');
    cursor.style.left = clientX + 'px';
    cursor.style.top = clientY + 'px';
    cursor.classList.add('active');
}

function sendCursorMsg(type, norm, extra) {
    if (!cursorSocket || cursorSocket.readyState !== 1) return;
    const payload = Object.assign({ type: type, x: norm.x, y: norm.y }, extra || {});
    cursorSocket.send(JSON.stringify(payload));
}

(function setupCursorTouchHandlers() {
    const wrap = document.getElementById('fs-screen-wrap');

    wrap.addEventListener('touchstart', function (e) {
        e.preventDefault();
        fsImgRect = computeImageRect();  // recompute in case of rotation/resize since last open
        touchFingerCount = e.touches.length;
        const t = e.touches[0];
        touchStartTime = Date.now();
        touchStartClientPos = { x: t.clientX, y: t.clientY };
        touchMoved = false;
        moveCursorOverlay(t.clientX, t.clientY);
        sendCursorMsg('move', clientPosToNormalized(t.clientX, t.clientY));
    }, { passive: false });

    wrap.addEventListener('touchmove', function (e) {
        e.preventDefault();
        const t = e.touches[0];
        if (touchStartClientPos && Math.hypot(t.clientX - touchStartClientPos.x, t.clientY - touchStartClientPos.y) > TAP_MAX_MOVE_PX) {
            touchMoved = true;
        }
        moveCursorOverlay(t.clientX, t.clientY);
        const now = Date.now();
        if (now - lastCursorSend > CURSOR_SEND_INTERVAL_MS) {
            sendCursorMsg('move', clientPosToNormalized(t.clientX, t.clientY));
            lastCursorSend = now;
        }
    }, { passive: false });

    wrap.addEventListener('touchend', function (e) {
        e.preventDefault();
        const heldMs = Date.now() - touchStartTime;
        if (!touchMoved && heldMs < TAP_MAX_MS && touchStartClientPos) {
            const norm = clientPosToNormalized(touchStartClientPos.x, touchStartClientPos.y);
            sendCursorMsg('click', norm, { button: touchFingerCount >= 2 ? 'right' : 'left' });
        }
        touchStartClientPos = null;
    }, { passive: false });
})();

// ---------- Text / confirmation flow ----------
let pendingConfirm = false;

async function transmitText() {
    if (isCallMode) return;
    const input = document.getElementById('cmdInput');
    const text = input.value.trim();
    if (!text) return;
    appendMessage("User", text);
    input.value = '';
    statusText.innerText = "ARGUS IS THINKING...";
    setIrisStatus('thinking');

    let form = new FormData();
    form.append("text", text);
    form.append("request_audio", "true");

    let response = await fetch("/command", { method: "POST", body: form });
    let data = await response.json();

    statusText.innerText = "SYSTEM IDLE";
    setIrisStatus('idle');
    appendMessage("Argus", data.log);
    playAudioResponse(data.audio_base64);

    if (data.log && data.log.toLowerCase().includes("say 'confirm' to proceed")) {
        document.getElementById('confirm-text').textContent = data.log;
        document.getElementById('confirm-banner').style.display = 'block';
        setIrisStatus('danger');
        pendingConfirm = true;
    }
}

async function sendConfirm(yes) {
    document.getElementById('confirm-banner').style.display = 'none';
    pendingConfirm = false;
    setIrisStatus('idle');
    const text = yes ? "confirm" : "cancel";
    appendMessage("User", text);
    let form = new FormData();
    form.append("text", text);
    form.append("request_audio", "true");
    let response = await fetch("/command", { method: "POST", body: form });
    let data = await response.json();
    appendMessage("Argus", data.log);
    playAudioResponse(data.audio_base64);
}

// ---------- Voice message ----------
async function toggleVoiceMessage() {
    if (isCallMode) return;
    const voiceBtn = document.getElementById('voiceBtn');
    if (!isRecording) {
        audioChunks = [];
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = e => audioChunks.push(e.data);

        mediaRecorder.onstop = async () => {
            statusText.innerText = "TRANSCRIBING...";
            setIrisStatus('thinking');
            const blob = new Blob(audioChunks, { type: 'audio/webm' });
            let form = new FormData();
            form.append("file", blob, "upload.webm");

            let response = await fetch("/voice", { method: "POST", body: form });
            let data = await response.json();

            appendMessage("User", data.transcript);
            appendMessage("Argus", data.log);
            statusText.innerText = "SYSTEM IDLE";
            setIrisStatus('idle');
            playAudioResponse(data.audio_base64);
        };
        mediaRecorder.start();
        isRecording = true;
        voiceBtn.textContent = "⏺ Recording... tap to send";
        voiceBtn.classList.add("active-rec");
        setIrisStatus('listening');
    } else {
        mediaRecorder.stop();
        isRecording = false;
        voiceBtn.textContent = "🎙 Voice Message";
        voiceBtn.classList.remove("active-rec");
    }
}

// ---------- Live call ----------
function toggleCallMode() {
    const callBtn = document.getElementById('callBtn');
    if (!isCallMode) {
        isCallMode = true;
        callBtn.textContent = "🔴 End Call";
        callBtn.classList.add("active-call");
        initWebSocket();
    } else {
        isCallMode = false;
        callBtn.textContent = "📞 Live Call";
        callBtn.classList.remove("active-call");
        statusText.innerText = "CALL ENDED";
        setIrisStatus('idle');
        if (ws) ws.close();
        if (mediaRecorder) mediaRecorder.stop();
    }
}

function initWebSocket() {
    const wsProtocol = window.location.protocol === "https:" ? "wss://" : "ws://";
    ws = new WebSocket(wsProtocol + window.location.host + "/stream");
    ws.binaryType = "arraybuffer";

    ws.onopen = async () => {
        statusText.innerText = "CONNECTED & LISTENING";
        setIrisStatus('listening');
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) ws.send(e.data);
        };
        mediaRecorder.start(400);
    };

    ws.onmessage = async (event) => {
        if (typeof event.data === "string") {
            const data = JSON.parse(event.data);
            if (data.type === "transcript") {
                appendMessage("User", data.text);
                statusText.innerText = "THINKING...";
                setIrisStatus('thinking');
            } else if (data.type === "reply") {
                appendMessage("Argus", data.text);
                statusText.innerText = "LISTENING...";
                setIrisStatus('listening');
            } else if (data.type === "notification") {
                showToast((data.source ? "[" + data.source + "] " : "") + data.text, data.level);
            } else if (data.type === "gatekeeper_otp") {
                showToast("Gatekeeper code for " + data.ip + ": " + data.code, "warning");
            }
        } else {
            audioQueue.push(event.data);
            if (!isPlaying) playNextAudioChunk();
        }
    };
}

function playNextAudioChunk() {
    if (audioQueue.length === 0) { isPlaying = false; return; }
    isPlaying = true;
    const chunk = audioQueue.shift();
    const blob = new Blob([chunk], { type: 'audio/wav' });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => playNextAudioChunk();
    audio.play();
}

// ---------- Protocol rail: toggles ----------
function toggleRail() {
    document.getElementById('protocol-rail').classList.toggle('open');
}

async function loadFeatures() {
    const res = await fetch('/api/features');
    const data = await res.json();
    allFeatures = data.features;
    renderFeatures();
}

function renderFeatures() {
    const categories = {};
    allFeatures.forEach(f => {
        if (!categories[f.category]) categories[f.category] = [];
        categories[f.category].push(f);
    });

    const container = document.getElementById('categoryContainer');
    container.innerHTML = '';
    let activeTotal = 0;

    Object.keys(categories).sort().forEach(cat => {
        const items = categories[cat];
        const activeInCat = items.filter(f => f.enabled).length;
        activeTotal += activeInCat;

        const block = document.createElement('div');
        block.className = 'category-block';
        block.innerHTML = `
            <div class="category-title">
                <span>${cat}</span>
                <span class="category-count">${activeInCat}/${items.length}</span>
            </div>
        `;
        items.forEach(f => {
            const row = document.createElement('div');
            row.className = 'protocol-row';
            row.innerHTML = `
                <div class="protocol-text">
                    <div class="protocol-name">${f.name}</div>
                    <div class="protocol-desc">${f.description}</div>
                </div>
                <label class="switch">
                    <input type="checkbox" ${f.enabled ? 'checked' : ''} onchange="onToggleFeature('${f.key}', this.checked)">
                    <span class="track"></span>
                </label>
            `;
            block.appendChild(row);
        });
        container.appendChild(block);
    });

    document.getElementById('activeCount').textContent = activeTotal;
}

async function onToggleFeature(key, enabled) {
    await fetch('/api/features/toggle', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, enabled })
    });
    showToast(`${key.replace(/_/g, ' ')} ${enabled ? 'enabled' : 'disabled'}`, enabled ? '' : 'warning');
    loadFeatures();
    if (key === 'castellan' && enabled) offerCastellanEnroll();
}

function offerCastellanEnroll() {
    if (confirm("Castellan enabled. Scan for your phone now to enroll it for proximity lock?")) {
        sendPrompt("enroll my phone for castellan");
    }
}

// ---------- Model selector ----------
async function loadModels() {
    const res = await fetch('/api/models');
    const data = await res.json();
    const select = document.getElementById('modelSelect');
    select.innerHTML = '';
    data.available.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m; opt.textContent = m;
        select.appendChild(opt);
    });
    document.getElementById('autoRouteToggle').checked = data.auto_routing_enabled;
    select.disabled = data.auto_routing_enabled;
    if (data.manual_selection) select.value = data.manual_selection;
}

async function onAutoRouteChange() {
    const enabled = document.getElementById('autoRouteToggle').checked;
    await fetch('/api/features/toggle', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'model_auto_routing', enabled })
    });
    document.getElementById('modelSelect').disabled = enabled;
    showToast(enabled ? 'Auto model routing enabled' : 'Manual model selection enabled');
}

async function onModelChange() {
    const model = document.getElementById('modelSelect').value;
    await fetch('/api/models/select', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model })
    });
    showToast('Model set to ' + model);
}

// ---------- Log History drawer ----------
function openDrawer() {
    document.getElementById('drawer').classList.add('open');
    document.getElementById('drawer-overlay').classList.add('open');
    loadDrawerContent();
}
function closeDrawer() {
    document.getElementById('drawer').classList.remove('open');
    document.getElementById('drawer-overlay').classList.remove('open');
}
function switchDrawerTab(tab) {
    drawerTab = tab;
    document.getElementById('tab-dev').classList.toggle('active', tab === 'dev');
    document.getElementById('tab-audit').classList.toggle('active', tab === 'audit');
    loadDrawerContent();
}

async function loadDrawerContent() {
    const body = document.getElementById('drawerBody');
    body.innerHTML = '<div class="empty-note">Loading...</div>';

    if (drawerTab === 'dev') {
        const res = await fetch('/api/self_dev/log');
        const data = await res.json();
        if (!data.log.length) {
            body.innerHTML = '<div class="empty-note">No self-development activity yet. Argus logs every diagnosis, patch proposal, and feature idea here — nothing is ever applied without your approval.</div>';
            return;
        }
        body.innerHTML = '';
        data.log.forEach(entry => {
            const div = document.createElement('div');
            div.className = 'log-entry';
            const badgeClass = entry.status === 'pending' ? 'badge-pending' : entry.status === 'approved' ? 'badge-approved' : entry.status === 'rejected' ? 'badge-rejected' : 'badge-info';
            const when = new Date(entry.created_at * 1000).toLocaleString();
            div.innerHTML = `
                <div class="log-meta"><span>${when}</span><span class="log-badge ${badgeClass}">${entry.status}</span></div>
                <div>${entry.summary || ''}</div>
                ${entry.diff_preview ? `<div class="log-diff">${entry.diff_preview.replace(/</g,'&lt;')}</div>` : ''}
                ${entry.kind === 'patch' && entry.status === 'pending' ? `
                    <div class="log-actions">
                        <button class="btn-approve" onclick="approvePatch('${entry.id}')">Approve &amp; apply</button>
                        <button class="btn-reject" onclick="rejectPatch('${entry.id}')">Reject</button>
                    </div>` : ''}
            `;
            body.appendChild(div);
        });
    } else {
        const res = await fetch('/audit');
        const data = await res.json();
        if (!data.actions.length) {
            body.innerHTML = '<div class="empty-note">No actions executed yet.</div>';
            return;
        }
        body.innerHTML = '';
        data.actions.forEach(a => {
            const div = document.createElement('div');
            div.className = 'log-entry';
            const when = new Date(a.timestamp * 1000).toLocaleString();
            div.innerHTML = `
                <div class="log-meta"><span>${when}</span><span class="log-badge badge-info">${a.action}</span></div>
                <div>${a.target || ''}</div>
                <div style="color:var(--text-faint); margin-top:4px;">${a.result || ''}</div>
            `;
            body.appendChild(div);
        });
    }
    refreshPendingDot();
}

async function approvePatch(id) {
    const res = await fetch('/api/self_dev/approve', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id })
    });
    const data = await res.json();
    showToast(data.result);
    loadDrawerContent();
}
async function rejectPatch(id) {
    const res = await fetch('/api/self_dev/reject', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id })
    });
    const data = await res.json();
    showToast(data.result);
    loadDrawerContent();
}

async function refreshPendingDot() {
    const res = await fetch('/api/self_dev/pending');
    const data = await res.json();
    document.getElementById('pendingDot').classList.toggle('show', data.pending.length > 0);
}

// ---------- Init ----------
loadFeatures();
loadModels();
refreshPendingDot();
setInterval(refreshPendingDot, 30000);

        </script>
    </body>
    </html>
    """


# --- PROTOCOL MIRAGE: BACKGROUND SCREEN GENERATOR ---
async def screen_stream_generator():
    """Captures the screen, aggressively compresses it to save RAM, and beams it to the phone."""
    while True:
        def grab_and_compress():
            img = ImageGrab.grab()
            # Resize image to save massive bandwidth and RAM
            img.thumbnail((800, 600))
            buf = io.BytesIO()
            # Compress to 40% quality. It's for surveillance, not 4K gaming.
            img.save(buf, format='JPEG', quality=40)
            return buf.getvalue()
        
        # Run the screen grab on a separate thread so it doesn't freeze the FastAPI server
        frame = await asyncio.to_thread(grab_and_compress)
        
        # Yield the image frame via MJPEG HTTP protocol
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
               
        # Restrict to 2 frames per second to save your 8GB laptop from melting
        await asyncio.sleep(0.5)

@app.get("/screen_feed")
async def screen_feed():
    """The endpoint the phone connects to for the live video feed."""
    return StreamingResponse(screen_stream_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


# --- PROTOCOL REMOTE CURSOR CONTROL ---
# Separate toggle from screen_feed on purpose: screen_feed is read-only
# (you can watch the laptop), this lets a connected phone actually MOVE
# and CLICK the real cursor -- a materially bigger capability, so it
# defaults off even though viewing doesn't gate behind anything.
#
# Coordinates over the wire are NORMALIZED (0.0-1.0 fractions of the
# screen), not raw pixels -- the phone doesn't need to know the
# laptop's actual resolution, just where on the DISPLAYED image it was
# touched. pyautogui.size() converts to real pixel coordinates here,
# server-side, once per connection.
@app.websocket("/ws/cursor")
async def cursor_control_websocket(websocket: WebSocket):
    # accept() FIRST, then close with the custom code if the toggle is
    # off -- closing before accepting doesn't properly propagate a
    # custom close code through the WebSocket handshake (the ASGI
    # server just refuses the HTTP Upgrade instead), so the browser was
    # seeing a generic abnormal disconnect rather than the intended
    # "toggle is off" message. Confirmed against a real screenshot
    # showing the generic fallback text instead of the specific one.
    await websocket.accept()
    if not feature_toggles.is_enabled("remote_cursor_control"):
        await websocket.close(code=4403, reason="Protocol Remote Cursor Control is toggled off.")
        return

    screen_w, screen_h = pyautogui.size()
    print(f"[Remote Cursor] Phone connected -- mapping to {screen_w}x{screen_h}.")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                x = max(0.0, min(1.0, float(msg.get("x", 0))))
                y = max(0.0, min(1.0, float(msg.get("y", 0))))
                px, py = round(x * screen_w), round(y * screen_h)
                msg_type = msg.get("type")

                # _pause=False skips pyautogui's default 0.1s pause after
                # every call -- with it left on, a drag would visibly
                # stutter at roughly 10 updates/sec no matter how fast
                # the phone sends them.
                if msg_type == "move":
                    pyautogui.moveTo(px, py, _pause=False)
                elif msg_type == "click":
                    button = msg.get("button", "left")
                    if button not in ("left", "right"):
                        button = "left"
                    pyautogui.click(px, py, button=button, _pause=False)
                elif msg_type == "doubleclick":
                    pyautogui.doubleClick(px, py, _pause=False)
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                print(f"[Remote Cursor] Ignored malformed message: {e}")
    except WebSocketDisconnect:
        print("[Remote Cursor] Phone disconnected.")
    except Exception as e:
        print(f"[Remote Cursor] Error: {e}")

# ---------------- Control Center: feature toggles ----------------
@app.get("/api/features")
async def api_list_features():
    return {"features": feature_toggles.list_all()}

@app.post("/api/features/toggle")
async def api_toggle_feature(request: Request):
    body = await request.json()
    key = body.get("key")
    enabled = bool(body.get("enabled"))
    if key not in feature_toggles.REGISTRY:
        return {"success": False, "error": "Unknown feature key."}
    feature_toggles.set_enabled(key, enabled)
    return {"success": True, "key": key, "enabled": enabled}

# ---------------- Control Center: model selection ----------------
@app.get("/api/models")
async def api_list_models():
    return {
        "available": model_router.AVAILABLE_MODELS,
        "manual_selection": model_router.get_manual_model(),
        "auto_routing_enabled": feature_toggles.is_enabled("model_auto_routing"),
    }

@app.post("/api/models/select")
async def api_select_model(request: Request):
    body = await request.json()
    model = body.get("model")  # None/null means "clear manual pick, defer to auto-routing"
    try:
        model_router.set_manual_model(model)
        return {"success": True, "model": model}
    except ValueError as e:
        return {"success": False, "error": str(e)}

# ---------------- Protocol Mirage Cam ----------------
@app.get("/camera_feed")
async def camera_feed():
    if not feature_toggles.is_enabled("mirage_cam"):
        return {"error": "Protocol Mirage Cam is currently toggled off."}
    return StreamingResponse(mirage_cam.camera_stream_generator(), media_type="multipart/x-mixed-replace; boundary=frame")

# ---------------- Protocol Castellan: enrollment ----------------
@app.get("/api/castellan/scan")
async def api_castellan_scan():
    try:
        devices = await castellan.scan_for_devices(timeout=6.0)
        return {"devices": devices}
    except Exception as e:
        return {"devices": [], "error": str(e)}

@app.post("/api/castellan/enroll")
async def api_castellan_enroll(request: Request):
    body = await request.json()
    message = castellan.enroll_device(body.get("mac_address", ""), body.get("name", ""))
    return {"success": True, "message": message}

# ---------------- Self-Development Engine: review queue ----------------
@app.get("/api/self_dev/log")
async def api_self_dev_log(limit: int = 100):
    return {"log": self_dev.get_log(limit)}

@app.get("/api/self_dev/pending")
async def api_self_dev_pending():
    return {"pending": self_dev.get_pending_patches()}

@app.post("/api/self_dev/approve")
async def api_self_dev_approve(request: Request):
    body = await request.json()
    result = await asyncio.to_thread(self_dev.approve_patch, body.get("id"))
    return {"result": result}

@app.post("/api/self_dev/reject")
async def api_self_dev_reject(request: Request):
    body = await request.json()
    result = await asyncio.to_thread(self_dev.reject_patch, body.get("id"))
    return {"result": result}

@app.post("/api/self_dev/run_cycle")
async def api_self_dev_run_cycle():
    await asyncio.to_thread(self_dev.run_cycle)
    return {"pending": self_dev.get_pending_patches()}

# ---------------- Feature 10: Document library web UI ----------------
import document_processor

@app.get("/documents")
async def list_documents():
    """Returns the manifest of every PDF ingested into the RAG library."""
    return {"documents": document_processor.list_ingested_documents()}

@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """Accepts a PDF upload, saves it into documents/, and ingests it into
    the FAISS RAG index so 'read_document' queries can use it immediately."""
    if not feature_toggles.is_enabled("document_library"):
        return {"success": False, "error": "Document Library is currently toggled off."}
    if not file.filename.lower().endswith(".pdf"):
        return {"success": False, "error": "Only PDF files are supported right now."}

    os.makedirs("documents", exist_ok=True)
    dest_path = os.path.join("documents", file.filename)
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    success = document_processor.ingest_pdf(dest_path)
    return {"success": success, "filename": file.filename}

@app.get("/library", response_class=HTMLResponse)
async def library_page():
    """A minimal standalone page for browsing/uploading the document library,
    separate from the main chat UI so it doesn't bloat that inline HTML."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Argus Document Library</title>
        <style>
            body { font-family: -apple-system, sans-serif; background:#0E1117; color:#E2E8F0; padding:20px; max-width:600px; margin:0 auto; }
            h1 { font-size: 1.3em; }
            .doc-card { background:#161B22; border:1px solid #30363D; padding:12px; border-radius:8px; margin-bottom:10px; }
            .doc-name { font-weight:600; }
            .doc-meta { color:#8B949E; font-size:0.85em; }
            input[type=file] { margin: 15px 0; }
            button { background:#238636; color:white; border:none; padding:8px 16px; border-radius:6px; cursor:pointer; }
            #status { margin-top:10px; color:#8B949E; }
        </style>
    </head>
    <body>
        <h1>📚 Argus Document Library</h1>
        <p>Upload PDFs here to make them queryable via "read_document" voice/text commands.</p>
        <form id="uploadForm">
            <input type="file" id="pdfFile" accept="application/pdf" required>
            <button type="submit">Upload &amp; Ingest</button>
        </form>
        <div id="status"></div>
        <h2>Ingested Documents</h2>
        <div id="docList">Loading...</div>

        <script>
        async function loadDocs() {
            const res = await fetch('/documents');
            const data = await res.json();
            const docList = document.getElementById('docList');
            if (!data.documents.length) {
                docList.innerHTML = '<p>No documents ingested yet.</p>';
                return;
            }
            docList.innerHTML = data.documents.map(d => `
                <div class="doc-card">
                    <div class="doc-name">${d.filename}</div>
                    <div class="doc-meta">${d.chunk_count} chunks &middot; ingested ${new Date(d.ingested_at * 1000).toLocaleString()}</div>
                </div>
            `).join('');
        }
        document.getElementById('uploadForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const fileInput = document.getElementById('pdfFile');
            const status = document.getElementById('status');
            if (!fileInput.files.length) return;
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            status.textContent = 'Uploading and ingesting...';
            const res = await fetch('/documents/upload', { method: 'POST', body: formData });
            const data = await res.json();
            status.textContent = data.success ? `Ingested ${data.filename}.` : `Failed: ${data.error || 'unknown error'}`;
            fileInput.value = '';
            loadDocs();
        });
        loadDocs();
        </script>
    </body>
    </html>
    """
# ------------------------------------------------------------------------

# ---------------- Protocol Virtual Terminal Extension: macro deck ----------------
# A fixed grid of named one-tap buttons for a phone, each bound to a saved
# (action, target) pair -- distinct from the freeform chat UI above (see
# macro_deck.py's module docstring for why this doesn't duplicate it).
import macro_deck

@app.get("/api/macros")
async def api_list_macros():
    return {"macros": macro_deck.load_macros(), "valid_actions": sorted(brain.VALID_ACTIONS)}

@app.post("/api/macros/add")
async def api_add_macro(request: Request):
    if not feature_toggles.is_enabled("virtual_terminal"):
        return {"success": False, "error": "Protocol Virtual Terminal Extension is currently toggled off."}
    body = await request.json()
    try:
        macro = macro_deck.add_macro(
            body.get("name", ""), body.get("action", ""),
            body.get("target", ""), body.get("icon") or "⚡",
        )
        return {"success": True, "macro": macro}
    except ValueError as e:
        return {"success": False, "error": str(e)}

@app.post("/api/macros/remove")
async def api_remove_macro(request: Request):
    body = await request.json()
    removed = macro_deck.remove_macro(body.get("name", ""))
    return {"success": removed}

@app.post("/api/macros/run")
async def api_run_macro(request: Request):
    if not feature_toggles.is_enabled("virtual_terminal"):
        return {"success": False, "error": "Protocol Virtual Terminal Extension is currently toggled off."}
    body = await request.json()
    # run_macro ultimately calls executor.run_local_command, which can block
    # (subprocess calls, file IO) -- off the event loop, same as self_dev's
    # endpoints above.
    result = await asyncio.to_thread(macro_deck.run_macro, body.get("name", ""))
    return {"success": True, "result": result}

@app.get("/macros", response_class=HTMLResponse)
async def macros_page():
    """A one-tap macro deck for a phone -- each button fires a saved
    (action, target) pair through the SAME executor.run_local_command
    dispatcher the chat interface uses (see macro_deck.py). Separate
    page, same reasoning as /library: keeps this out of the main chat
    UI's inline HTML."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Argus Macro Deck</title>
        <style>
            body { font-family: -apple-system, sans-serif; background:#0E1117; color:#E2E8F0; padding:20px; max-width:600px; margin:0 auto; }
            h1 { font-size: 1.3em; }
            .grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap:10px; margin:15px 0; }
            .macro-btn { background:#161B22; border:1px solid #30363D; border-radius:10px; padding:16px 8px; text-align:center; cursor:pointer; color:#E2E8F0; }
            .macro-btn:active { background:#238636; }
            .macro-icon { font-size:1.8em; }
            .macro-name { font-size:0.8em; color:#8B949E; margin-top:6px; }
            .remove-x { float:right; color:#8B949E; cursor:pointer; }
            form { background:#161B22; border:1px solid #30363D; padding:14px; border-radius:8px; margin-top:20px; }
            input, select { width:100%; box-sizing:border-box; margin-bottom:8px; padding:8px; background:#0E1117; color:#E2E8F0; border:1px solid #30363D; border-radius:6px; }
            button[type=submit] { background:#238636; color:white; border:none; padding:8px 16px; border-radius:6px; cursor:pointer; }
            #status { margin-top:10px; color:#8B949E; min-height:1.2em; }
        </style>
    </head>
    <body>
        <h1>⚡ Argus Macro Deck</h1>
        <div class="grid" id="macroGrid">Loading...</div>

        <form id="addForm">
            <strong>Add a macro</strong>
            <input type="text" id="mName" placeholder="Name (e.g. Deploy)" required>
            <select id="mAction" required></select>
            <input type="text" id="mTarget" placeholder="Target (e.g. filename, or the command)">
            <input type="text" id="mIcon" placeholder="Icon (emoji, optional)" maxlength="2">
            <button type="submit">Save Macro</button>
        </form>
        <div id="status"></div>

        <script>
        let allMacros = [];
        async function loadMacros() {
            const res = await fetch('/api/macros');
            const data = await res.json();
            allMacros = data.macros;
            const grid = document.getElementById('macroGrid');
            grid.innerHTML = allMacros.length ? allMacros.map(m => `
                <div class="macro-btn" onclick="runMacro('${m.name}')">
                    <span class="remove-x" onclick="event.stopPropagation(); removeMacro('${m.name}')">&times;</span>
                    <div class="macro-icon">${m.icon}</div>
                    <div class="macro-name">${m.name}</div>
                </div>
            `).join('') : '<p>No macros saved yet -- add one below.</p>';

            const select = document.getElementById('mAction');
            select.innerHTML = data.valid_actions.map(a => `<option value="${a}">${a}</option>`).join('');
        }
        async function runMacro(name) {
            const status = document.getElementById('status');
            status.textContent = `Running "${name}"...`;
            const res = await fetch('/api/macros/run', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name}),
            });
            const data = await res.json();
            status.textContent = data.success ? `Done: ${data.result}` : `Failed: ${data.error || 'unknown error'}`;
        }
        async function removeMacro(name) {
            await fetch('/api/macros/remove', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name}),
            });
            loadMacros();
        }
        document.getElementById('addForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const status = document.getElementById('status');
            const payload = {
                name: document.getElementById('mName').value,
                action: document.getElementById('mAction').value,
                target: document.getElementById('mTarget').value,
                icon: document.getElementById('mIcon').value,
            };
            const res = await fetch('/api/macros/add', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            status.textContent = data.success ? `Saved "${payload.name}".` : `Failed: ${data.error}`;
            if (data.success) {
                document.getElementById('addForm').reset();
                loadMacros();
            }
        });
        loadMacros();
        </script>
    </body>
    </html>
    """
# ------------------------------------------------------------------------------

# ---------------- Feature 12: Audit log viewer ----------------
import audit

@app.get("/audit")
async def get_audit_log(limit: int = 50):
    """Returns the most recent executed actions (open_app, system_command,
    git_push, etc.) with their results and timestamps."""
    return {"actions": audit.get_recent_actions(limit)}
# ----------------------------------------------------------------
# ----------------------------------------------------

_pending_confirmation = {"action": None, "target": None}

async def core_logic(text: str):
    # Feature 4: if a risky action is awaiting confirmation, this message
    # is treated as the yes/no answer instead of being reclassified.
    if _pending_confirmation["action"] is not None:
        pending_action = _pending_confirmation["action"]
        pending_target = _pending_confirmation["target"]
        _pending_confirmation["action"] = None
        _pending_confirmation["target"] = None
        if safety.is_confirmation(text):
            return run_local_command(pending_action, pending_target)
        return "Okay, cancelled. No changes made."

    decision = await process_command(text, is_stream=False)
    action = decision.get("action")
    target = decision.get("target")

    if action == "casual_chat":
        return target
    elif action in ["open_app", "system_command", "vision_task", "room_awareness", "read_file", "run_script", "deep_research", "read_clipboard", "ghost_type", "connect_app", "schedule_task", "git_push", "calendar", "send_email", "castellan_enroll", "git_archeology", "dataset_synth", "multi_agent_council", "syntax_guardian_check", "log_digest", "mind_map_export", "scraping_vanguard", "synthetic_anchor", "auto_documentation", "self_dev_status"]:
        if safety.is_risky(action, target):
            _pending_confirmation["action"] = action
            _pending_confirmation["target"] = target
            return safety.confirmation_prompt(action, target)
        return run_local_command(action, target)
    return f"I executed the {action} sequence."

@app.post("/command")
async def handle_text(text: str = Form(...), request_audio: str = Form("false")):
    reply = await core_logic(text)
    audio = generate_speech_base64(reply) if request_audio == "true" else None
    return {"log": reply, "audio_base64": audio}

@app.post("/command_stream")
async def handle_text_stream(text: str = Form(...)):
    """Feature 2: Server-Sent Events endpoint. For casual_chat replies this
    streams tokens as Ollama generates them instead of waiting for the full
    reply. Non-chat actions (open_app, system_command, etc.) still run to
    completion first since there's nothing meaningful to stream mid-execution,
    but the result is still delivered over the same SSE connection."""

    async def event_stream():
        # Same pending-confirmation handling as core_logic, so risky actions
        # stay gated even on the streaming endpoint.
        if _pending_confirmation["action"] is not None:
            pending_action = _pending_confirmation["action"]
            pending_target = _pending_confirmation["target"]
            _pending_confirmation["action"] = None
            _pending_confirmation["target"] = None
            if safety.is_confirmation(text):
                result = run_local_command(pending_action, pending_target)
            else:
                result = "Okay, cancelled. No changes made."
            yield f"data: {json.dumps({'token': result})}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        decision = await process_command(text, is_stream=True)
        action = decision.get("action")
        target = decision.get("target")

        if action == "casual_chat" and target == "STREAM":
            async for token in brain.stream_casual_reply(text):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        if action == "casual_chat":
            yield f"data: {json.dumps({'token': target})}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        if action in ["open_app", "system_command", "vision_task", "room_awareness", "read_file", "run_script", "deep_research", "read_clipboard", "ghost_type", "connect_app", "schedule_task", "git_push", "calendar", "send_email", "castellan_enroll", "git_archeology", "dataset_synth", "multi_agent_council", "syntax_guardian_check", "log_digest", "mind_map_export", "scraping_vanguard", "synthetic_anchor", "auto_documentation", "self_dev_status"]:
            if safety.is_risky(action, target):
                _pending_confirmation["action"] = action
                _pending_confirmation["target"] = target
                result = safety.confirmation_prompt(action, target)
            else:
                result = run_local_command(action, target)
            yield f"data: {json.dumps({'token': result})}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        yield f"data: {json.dumps({'token': f'I executed the {action} sequence.'})}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/voice")
async def handle_voice(file: UploadFile = File(...)):
    path = "audio_cache/remote_input.webm"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
        
    text = transcribe_audio(path)
    if not text:
        return {"transcript": "(Inaudible)", "log": "I didn't catch that.", "audio_base64": None}
        
    reply = await core_logic(text)
    return {"transcript": text, "log": reply, "audio_base64": generate_speech_base64(reply)}

async def stream_sentence_audio(text_input, websocket: WebSocket):
    """Streams a casual_chat reply sentence-by-sentence as TTS audio.
    Uses brain.stream_casual_reply so the persona prompt, model choice,
    and history/DB logging stay consistent with the non-streaming path
    (previously this had its own separate persona prompt and never saved
    the reply to history or the database)."""
    current_sentence = ""
    full_reply = ""

    async for token in brain.stream_casual_reply(text_input):
        current_sentence += token
        full_reply += token

        if any(punct in token for punct in ['.', '?', '!']):
            clean_sentence = current_sentence.strip()
            if clean_sentence:
                audio_tensor = tts_model.apply_tts(text=clean_sentence, speaker='en_16', sample_rate=48000)
                buffer = io.BytesIO()
                sf.write(buffer, audio_tensor.numpy(), 48000, format='WAV')
                buffer.seek(0)
                await websocket.send_bytes(buffer.read())
            current_sentence = ""

    await websocket.send_text(json.dumps({"type": "reply", "text": full_reply}))

@app.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    audio_buffer = io.BytesIO()
    # Feature 4: pending confirmation state scoped to this one voice connection.
    ws_pending_confirmation = {"action": None, "target": None}
    
    try:
        while True:
            data = await websocket.receive_bytes()
            audio_buffer.write(data)
            
            if audio_buffer.tell() > 60000:
                audio_buffer.seek(0)
                try:
                    segment = AudioSegment.from_file(audio_buffer, format="webm")
                    wav_io = io.BytesIO()
                    segment.export(wav_io, format="wav")
                    wav_io.seek(0)
                    
                    with open("audio_cache/stream_chunk.wav", "wb") as f:
                        f.write(wav_io.read())
                        
                    tanglish_primer = "Hello macha, epdi irukka? What are you doing bro? Seri, let's start."
                    text = whisper_model.transcribe("audio_cache/stream_chunk.wav", fp16=False, initial_prompt=tanglish_primer)["text"].strip()
                    
                    if len(text) > 3:
                        await websocket.send_text(json.dumps({"type": "transcript", "text": text}))

                        # If a risky action is awaiting confirmation, this
                        # utterance is the yes/no answer, not a new command.
                        if ws_pending_confirmation["action"] is not None:
                            pending_action = ws_pending_confirmation["action"]
                            pending_target = ws_pending_confirmation["target"]
                            ws_pending_confirmation["action"] = None
                            ws_pending_confirmation["target"] = None
                            if safety.is_confirmation(text):
                                result = run_local_command(pending_action, pending_target)
                            else:
                                result = "Okay, cancelled. No changes made."
                            audio_tensor = tts_model.apply_tts(text=result, speaker='en_16', sample_rate=48000)
                            buffer = io.BytesIO()
                            sf.write(buffer, audio_tensor.numpy(), 48000, format='WAV')
                            buffer.seek(0)
                            await websocket.send_bytes(buffer.read())
                            await websocket.send_text(json.dumps({"type": "reply", "text": result}))
                            audio_buffer = io.BytesIO()
                            continue
                        
                        decision = await process_command(text, is_stream=True)
                        action = decision.get("action")
                        target = decision.get("target")
                        
                        if action in ["open_app", "system_command", "vision_task", "room_awareness", "read_file", "run_script", "deep_research", "read_clipboard", "ghost_type", "connect_app", "schedule_task", "git_push", "calendar", "send_email", "castellan_enroll", "git_archeology", "dataset_synth", "multi_agent_council", "syntax_guardian_check", "log_digest", "mind_map_export", "scraping_vanguard", "synthetic_anchor", "auto_documentation", "self_dev_status"]:
                            if safety.is_risky(action, target):
                                ws_pending_confirmation["action"] = action
                                ws_pending_confirmation["target"] = target
                                result = safety.confirmation_prompt(action, target)
                            else:
                                result = run_local_command(action, target)
                            audio_tensor = tts_model.apply_tts(text=result, speaker='en_16', sample_rate=48000)
                            buffer = io.BytesIO()
                            sf.write(buffer, audio_tensor.numpy(), 48000, format='WAV')
                            buffer.seek(0)
                            await websocket.send_bytes(buffer.read())
                            await websocket.send_text(json.dumps({"type": "reply", "text": result}))
                        
                        elif action == "casual_chat":
                            if target == "STREAM":
                                await stream_sentence_audio(text, websocket)
                            else:
                                audio_tensor = tts_model.apply_tts(text=target, speaker='en_16', sample_rate=48000)
                                buffer = io.BytesIO()
                                sf.write(buffer, audio_tensor.numpy(), 48000, format='WAV')
                                buffer.seek(0)
                                await websocket.send_bytes(buffer.read())
                                await websocket.send_text(json.dumps({"type": "reply", "text": target}))
                                
                except Exception as e:
                    pass
                audio_buffer = io.BytesIO()
    except WebSocketDisconnect:
        print("[Stream] Client disconnected.")
    finally:
        connected_clients.discard(websocket)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)