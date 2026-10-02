"""
feature_toggles.py — Central on/off registry for every Argus protocol.

Every feature added across this project (the original 12 upgrades, and
the 16 new "Protocols" below) is registered here with a stable key, a
display name/category for the UI, and a safe default. The control-center
UI reads this to render toggle switches; every module checks
is_enabled(key) before doing its thing, so flipping a switch off in the
UI actually disables the feature at runtime rather than just hiding it
visually.

State persists to feature_toggles.json so it survives restarts.
"""

import json
import os
import threading

STATE_FILE = "feature_toggles.json"
_lock = threading.Lock()

# key -> (display_name, category, default_enabled, description)
REGISTRY = {
    # --- Core upgrades (previous pass) ---
    "streaming_replies":      ("Streaming Replies", "Core", True, "Token-by-token streamed chat responses."),
    "semantic_memory":        ("Semantic Memory", "Core", True, "Recall relevant past conversations via FAISS."),
    "risk_confirmation":      ("Risk Confirmation", "Safety", True, "Require a confirm step before destructive actions."),
    "proactive_notifications":("Proactive Notifications", "Core", True, "Push watchdog alerts to connected clients."),
    "workflow_checkpointing": ("Workflow Checkpointing", "Core", True, "Autonomous workflows can pause and ask a question."),
    "voice_id":               ("Voice ID Gate", "Safety", False, "Gate risky actions to your enrolled voiceprint."),
    "calendar_email":         ("Calendar & Email", "Productivity", True, "Local calendar + SMTP email actions."),
    "model_auto_routing":     ("Auto Model Routing", "Core", True, "Pick model by task complexity instead of a fixed model."),
    "document_library":       ("Document Library", "Productivity", True, "RAG over uploaded PDFs."),
    "audit_log":              ("Audit Log", "Safety", True, "Log every executed action to the vault DB."),

    # --- New Protocols ---
    "castellan":              ("Protocol Castellan", "Security", False, "Bluetooth proximity auto-lock."),
    "mirage_cam":             ("Protocol Mirage Cam", "Security", False, "Stream the webcam to your phone dashboard."),
    "git_archeologist":       ("Protocol Git Archeologist", "Developer", True, "Visual commit dependency map."),
    "dataset_synth":          ("Protocol Dataset Synth", "Developer", True, "Generate large local mock datasets."),
    "multi_agent_council":    ("Protocol Multi-Agent Council", "Developer", True, "Two local LLMs debate a design before coding."),
    "lazarus_self_healing":   ("Protocol Lazarus (Self-Healing)", "Reliability", True, "Auto-restart crashed services with backoff."),
    "radio_silence":          ("Protocol Radio Silence", "Connectivity", False, "Raw LAN socket command server, no internet."),
    "smart_dictation":        ("Protocol Smart Dictation", "Productivity", False, "Global hotkey voice-to-text into any field."),
    "syntax_guardian":        ("Protocol Syntax Guardian", "Developer", True, "Auto-lint/format before Protocol Shadow pushes."),
    "smart_log_digest":       ("Protocol Smart Log Digest", "Productivity", True, "Daily 2-line Tanglish audio summary."),
    "mind_map_exporter":      ("Protocol Mind Map Exporter", "Developer", True, "Render the project graph as interactive HTML."),
    "scraping_vanguard":      ("Protocol Scraping Vanguard", "Research", False, "Rate-limited public data / dataset / deadline fetcher."),
    "synthetic_anchor":       ("Protocol Synthetic Anchor", "Research", True, "Local semantic search over your own notes/code/docs."),
    "rss_aggregator":         ("Protocol RSS Aggregator", "Research", False, "Background dev/AI news digest."),
    "auto_documentation":     ("Protocol Auto-Documentation", "Developer", True, "Auto-insert docstrings into a script."),
    "gatekeeper_mfa":         ("Protocol Gatekeeper", "Security", False, "OTP verification for new-IP dashboard logins."),
    "self_dev_engine":        ("Self-Development Engine", "Autonomy", False, "Argus drafts self-patches for your review (never auto-applies)."),

    # --- New Protocols (this pass): multi-agent Round Table + 13 requested protocols ---
    "round_table":            ("Protocol Round Table", "Agents", True, "Auto-assembled team of specialist personas for complex/multi-domain tasks."),
    "context_compaction":     ("Protocol Semantic Context Compaction", "Core", True, "Trims low-signal lines from context before it hits the fast model."),
    "tiled_attention":        ("Protocol Flash-Attention Emulation", "Developer", True, "Memory-bounded tiled attention (NumPy) -- see its own docstring on what it can't do."),
    "sequence_sharding":      ("Protocol Dynamic Sequence Sharding", "Developer", True, "Map-reduce analysis for logs/codebases too large for one pass."),
    "virtual_terminal":       ("Protocol Virtual Terminal Extension", "Productivity", False, "Phone macro deck -- one-tap buttons bound to saved actions."),
    "zero_g_visual":          ("Protocol Zero-G Visual Controls", "Productivity", False, "Webcam hand-gesture shortcuts (stop/pause/clear/screenshot)."),
    "shadow_sandbox":         ("Protocol Shadow Sandbox Execution", "Safety", True, "Runs generated scripts isolated (Docker if available, else a restricted subprocess)."),
    "complexity_auditor":     ("Protocol Big-O Complexity Auditor", "Developer", True, "Heuristic static analysis of a script's time complexity."),
    "db_index_optimizer":     ("Protocol Database Indexing Optimizer", "Developer", True, "EXPLAIN QUERY PLAN + timing analysis; suggests/creates indexes (report-first)."),
    "sql_to_nosql":           ("Protocol Relational-to-NoSQL Transpiler", "Developer", True, "Maps CREATE TABLE schemas to a MongoDB-style document schema."),
    "acoustic_link":          ("Protocol Acoustic Data Link", "Connectivity", False, "Short alerts over near-ultrasonic audio tones when the network is down."),
    "graph_sync":             ("Protocol Peer-to-Peer Graph Sync", "Connectivity", False, "Encrypted LAN sync of the knowledge graph across your devices."),
    "off_peak_harvester":     ("Protocol Off-Peak Data Harvesting", "Research", False, "Scheduled fetch of your configured public sources during off-peak hours."),
    "mcp_bridge":             ("Protocol MCP Tool Bridge", "Connectivity", False, "Local (stdio-only) MCP tool servers you explicitly configure -- nothing pre-connected, no network exposure."),
    "frontier_escalation":    ("Protocol Frontier Escalation", "Connectivity", False, "Opt-in, confirmed-only escalation to a real cloud model for questions beyond local capability."),
    "no_slop":                ("Protocol No Slop", "Core", True, "Strips generic AI-writing filler from responses -- doesn't touch Argus's actual personality/slang."),
    "remote_cursor_control":  ("Protocol Remote Cursor Control", "Security", False, "Lets the full-screen phone view actually move/click the laptop's real cursor, not just watch it."),
    "remote_launcher":        ("Protocol Wireless Launcher", "Security", False, "Phone app can start Argus remotely via PIN+password-gated HMAC auth -- fails closed if this is off."),
    "power_throttle":         ("Protocol Smart Power Throttling", "Reliability", True, "Shrinks token budgets / polling intervals automatically when on battery."),
}

_state_cache = None


def _load():
    global _state_cache
    if _state_cache is not None:
        return _state_cache
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                _state_cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            _state_cache = {}
    else:
        _state_cache = {}
    # Fill in defaults for any key not yet persisted
    changed = False
    for key, (_, _, default, _) in REGISTRY.items():
        if key not in _state_cache:
            _state_cache[key] = default
            changed = True
    if changed:
        _save(_state_cache)
    return _state_cache


def _save(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_enabled(key: str) -> bool:
    """Returns whether a feature is currently toggled on. Unknown keys
    default to True so a typo never silently disables something."""
    with _lock:
        state = _load()
        return state.get(key, True)


def set_enabled(key: str, enabled: bool):
    with _lock:
        state = _load()
        state[key] = bool(enabled)
        _save(state)
        global _state_cache
        _state_cache = state


def list_all():
    """Returns the full registry annotated with current state, grouped
    for the UI: [{"key", "name", "category", "description", "enabled"}]"""
    with _lock:
        state = _load()
    return [
        {
            "key": key,
            "name": name,
            "category": category,
            "description": desc,
            "enabled": state.get(key, default),
        }
        for key, (name, category, default, desc) in REGISTRY.items()
    ]
