"""
notifier.py — Feature 5: Proactive notifications.

overwatch.py, security_warden.py, aegis.py, and the Chronos scheduler
all run as separate OS processes from remote_server.py, so they can't
call into its in-memory websocket connection list directly. Instead,
they append alerts to a shared JSON-lines file, and remote_server.py
runs a background task that tails that file and broadcasts new lines
to every connected websocket client.

This keeps every watchdog decoupled — they don't need to know whether
anyone is even listening.
"""

import json
import os
import time

ALERTS_FILE = "audio_cache/alerts_outbox.jsonl"


def queue_alert(source: str, message: str, level: str = "info"):
    """Appends an alert for remote_server.py to pick up and broadcast.
    source: which watchdog raised it (e.g. "overwatch", "aegis").
    level: "info" | "warning" | "critical" — lets the UI style it.
    No-ops if the "proactive_notifications" toggle is off.
    """
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("proactive_notifications"):
            return
    except Exception:
        pass

    os.makedirs(os.path.dirname(ALERTS_FILE), exist_ok=True)
    entry = {
        "source": source,
        "message": message,
        "level": level,
        "timestamp": time.time(),
    }
    try:
        with open(ALERTS_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[Notifier Error] Failed to queue alert: {e}")


def drain_new_alerts(last_offset: int):
    """Reads any alert lines appended since last_offset (a byte offset
    into ALERTS_FILE). Returns (alerts, new_offset). Safe to call even
    if the file doesn't exist yet."""
    if not os.path.exists(ALERTS_FILE):
        return [], last_offset

    alerts = []
    with open(ALERTS_FILE, "r") as f:
        f.seek(last_offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                alerts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        new_offset = f.tell()

    return alerts, new_offset
