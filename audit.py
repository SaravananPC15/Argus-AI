"""
audit.py — Feature 12: Audit log / action history.

executor.run_local_command is called synchronously from many different
contexts (hands.py's voice loop, wake_agent.py's threads, agent_orchestrator's
workflow steps, remote_server.py's async handlers). database.py's dialogue
log is async (aiosqlite) and awkward to call from all of those. This module
uses plain stdlib sqlite3 so any caller, sync or async, can log an action
with a single call and no event loop required.

Stored in the same DB file as database.py (argus_vault.db) but in its own
table, so a single "vault" file still holds everything.
"""

import sqlite3
import time
import os

DB_PATH = "argus_vault.db"


def _get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            target TEXT,
            result TEXT,
            timestamp REAL
        )
    """)
    return conn


def log_action(action: str, target: str, result: str):
    """Records one executed action. Never raises — a logging failure
    should never take down the action it's trying to log. No-ops if the
    "audit_log" toggle is off (existing history stays readable either way)."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("audit_log"):
            return
    except Exception:
        pass

    try:
        conn = _get_connection()
        with conn:
            conn.execute(
                "INSERT INTO action_logs (action, target, result, timestamp) VALUES (?, ?, ?, ?)",
                (action, str(target)[:500], str(result)[:1000], time.time())
            )
        conn.close()
    except Exception as e:
        print(f"[Audit Error] Failed to log action: {e}")


def get_recent_actions(limit: int = 50):
    """Returns the most recent logged actions, newest first, as a list
    of dicts: {id, action, target, result, timestamp}."""
    try:
        conn = _get_connection()
        cursor = conn.execute(
            "SELECT id, action, target, result, timestamp FROM action_logs ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "action": r[1], "target": r[2], "result": r[3], "timestamp": r[4]}
            for r in rows
        ]
    except Exception as e:
        print(f"[Audit Error] Failed to fetch action log: {e}")
        return []
