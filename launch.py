#!/usr/bin/env python3
"""
Argus Unified Launcher / Process Supervisor
============================================
Starts the Argus service scripts as managed subprocesses, tags and colors
their output so you can tell them apart in one terminal, restarts anything
that crashes (with backoff), and shuts everything down cleanly on Ctrl+C.

This replaces manually opening 4-6 terminals for main.py / wake_agent.py /
remote_server.py / overwatch.py / security_warden.py / aegis.py / sentinel.py.

USAGE
-----
    python launch.py                        # remote_server.py + all watchdogs
    python launch.py --mode wake            # wake_agent.py instead of remote_server
    python launch.py --mode legacy          # main.py (the simple mic-loop version)
    python launch.py --minimal              # only the chosen core mode, nothing else
    python launch.py --no-watchdogs         # core mode without the background monitors
    python launch.py --with vision_stream forge   # add optional extras
    python launch.py --list                 # show every known service and exit

Logs for every service are written to ./logs/<service_name>.log as well as
printed live to this terminal, prefixed with the service name.

NOTE: --mode remote and --mode wake both want the microphone. Don't run two
core modes at once — pick the one you want with --mode.
"""

import argparse
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

# ----------------------------------------------------------------------
# Service registry
# ----------------------------------------------------------------------
# "core"     : the main interaction entrypoint -- pick exactly ONE via --mode
# "watchdog" : background monitors, on by default, safe to run together
# "extra"    : optional features, opt-in via --with
#
# toggle_key, where present, ties a service to feature_toggles.py: the
# Supervisor checks it live (not just at startup) and starts/stops the
# service to match whatever's set in the control-center UI, without
# treating a toggle-driven stop as a crash.

CORE_SERVICES = {
    "remote": {
        "script": "remote_server.py",
        "desc": "FastAPI web/phone uplink (voice, text, screen share, control center)",
    },
    "wake": {
        "script": "wake_agent.py",
        "desc": "Local clap/wake-word triggered voice loop",
    },
    "legacy": {
        "script": "main.py",
        "desc": "Legacy simple mic-loop assistant",
    },
}

WATCHDOG_SERVICES = {
    "overwatch": {
        "script": "overwatch.py",
        "desc": "Network anomaly monitor",
    },
    "security_warden": {
        "script": "security_warden.py",
        "desc": "Vault file-tamper monitor",
    },
    "aegis": {
        "script": "aegis.py",
        "desc": "CPU / battery health monitor",
    },
    "sentinel": {
        "script": "sentinel.py",
        "desc": "Watches .py files for syntax errors on save",
    },
}

EXTRA_SERVICES = {
    "forge": {
        "script": "forge.py",
        "desc": "Auto-sorts files dropped into the inbox folder",
    },
    "vision_stream": {
        "script": "vision_stream.py",
        "desc": "Webcam object-detection feed for room_awareness",
    },
    "tactical_hud": {
        "script": "tactical_hud.py",
        "desc": "Transparent on-screen overlay (Windows only)",
    },
    "dashboard": {
        "script": "dashboard.py",
        "desc": "Streamlit control panel",
        "runner": ["streamlit", "run"],
    },
    # --- New Protocol background services ---
    "castellan": {
        "script": "castellan.py",
        "desc": "Protocol Castellan — Bluetooth proximity auto-lock",
        "toggle_key": "castellan",
    },
    "radio_silence": {
        "script": "radio_silence.py",
        "desc": "Protocol Radio Silence — raw LAN socket command server",
        "toggle_key": "radio_silence",
    },
    "smart_dictation": {
        "script": "smart_dictation.py",
        "desc": "Protocol Smart Dictation — global hotkey voice-to-text",
        "toggle_key": "smart_dictation",
    },
    "rss_aggregator": {
        "script": "rss_aggregator.py",
        "desc": "Protocol RSS Aggregator — background tech-news digest",
        "toggle_key": "rss_aggregator",
    },
    "self_dev": {
        "script": "self_dev_daemon.py",
        "desc": "Self-Development Engine — self-diagnosis + patch proposals",
        "toggle_key": "self_dev_engine",
    },
    "gesture_control": {
        "script": "gesture_control_service.py",
        "desc": "Protocol Zero-G Visual Controls — webcam hand-gesture shortcuts",
        "toggle_key": "zero_g_visual",
    },
    "power_throttle": {
        "script": "power_throttle_service.py",
        "desc": "Protocol Smart Power Throttling — battery-aware token/polling scaling",
        "toggle_key": "power_throttle",
    },
    "off_peak_harvester": {
        "script": "off_peak_harvester_service.py",
        "desc": "Protocol Off-Peak Data Harvesting — scheduled fetch of configured sources",
        "toggle_key": "off_peak_harvester",
    },
    "graph_sync": {
        "script": "graph_sync_service.py",
        "desc": "Protocol Peer-to-Peer Graph Sync — LAN discovery + serve nexus_graph.json",
        "toggle_key": "graph_sync",
    },
}

# ----------------------------------------------------------------------
# Crash classification (Protocol Lazarus)
# ----------------------------------------------------------------------
# Transient errors are things that are expected to resolve themselves
# (a mic device momentarily busy, a dropped websocket, a flaky network
# call) -- these get near-instant restarts and don't count against the
# backoff budget. Anything else is treated as a real bug and backs off
# exponentially so a genuinely broken service doesn't spin forever.
_TRANSIENT_ERROR_PATTERNS = [
    r"PyAudio", r"ALSA", r"portaudio", r"audio.*exception", r"winsound",
    r"WebSocketDisconnect", r"ConnectionReset", r"ConnectionRefused",
    r"BrokenPipeError", r"TimeoutError", r"BleakError", r"bluetooth.*busy",
]
_TRANSIENT_RE = re.compile("|".join(_TRANSIENT_ERROR_PATTERNS), re.IGNORECASE)


def _classify_crash(tail_text: str) -> str:
    """Returns 'transient' or 'unknown' based on the tail of a crashed
    service's log output."""
    if _TRANSIENT_RE.search(tail_text or ""):
        return "transient"
    return "unknown"

# ----------------------------------------------------------------------
# Console colors (skip gracefully when not attached to a real terminal)
# ----------------------------------------------------------------------
_COLOR_CODES = ["\033[36m", "\033[35m", "\033[33m", "\033[32m", "\033[34m", "\033[31m", "\033[96m", "\033[95m"]
_RESET = "\033[0m"
_USE_COLOR = sys.stdout.isatty()


def _color_for(index):
    if not _USE_COLOR:
        return "", ""
    return _COLOR_CODES[index % len(_COLOR_CODES)], _RESET


# ----------------------------------------------------------------------
# A single managed subprocess
# ----------------------------------------------------------------------
class ManagedService:
    MAX_RESTARTS = 5
    BACKOFF_BASE_SECONDS = 2  # doubles on each successive restart
    TRANSIENT_RESTART_SECONDS = 1  # Protocol Lazarus: near-instant retry for known-flaky errors
    LOG_TAIL_LINES = 25

    def __init__(self, name, script, desc, index, python_exe, project_dir, log_dir, runner=None, toggle_key=None):
        self.name = name
        self.script = script
        self.desc = desc
        self.python_exe = python_exe
        self.project_dir = project_dir
        self.log_dir = log_dir
        self.runner = runner  # e.g. ["streamlit", "run"] instead of [python, script]
        self.toggle_key = toggle_key
        self.process = None
        self.restarts = 0
        self.transient_restarts = 0
        self.stopped_intentionally = False
        self.stopped_by_toggle = False
        self.color, self.reset = _color_for(index)
        self.log_path = os.path.join(log_dir, f"{name}.log")
        self._log_file = None
        self._recent_lines = []

    def _build_cmd(self):
        if self.runner:
            return self.runner + [self.script]
        return [self.python_exe, "-u", self.script]

    def start(self):
        if self.toggle_key and not self._toggle_is_enabled():
            self._print(f"SKIPPED — '{self.toggle_key}' is toggled off in the control center")
            self.stopped_by_toggle = True
            return False

        script_path = os.path.join(self.project_dir, self.script)
        if not os.path.exists(script_path):
            self._print(f"SKIPPED — {self.script} not found in project folder")
            return False

        self.stopped_by_toggle = False
        self._log_file = open(self.log_path, "a", buffering=1, encoding="utf-8")
        self._log_file.write(f"\n=== started {datetime.now().isoformat()} ===\n")

        cmd = self._build_cmd()
        self._print(f"starting  ({' '.join(cmd)})")

        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=self.project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as e:
            self._print(f"FAILED TO START — {e}")
            return False

        threading.Thread(target=self._pump_output, daemon=True).start()
        return True

    def _toggle_is_enabled(self) -> bool:
        try:
            import feature_toggles
            return feature_toggles.is_enabled(self.toggle_key)
        except Exception:
            return True  # fail open rather than silently never starting a service

    def _pump_output(self):
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            line = line.rstrip("\n")
            if self._log_file:
                self._log_file.write(line + "\n")
            self._recent_lines.append(line)
            if len(self._recent_lines) > self.LOG_TAIL_LINES:
                self._recent_lines.pop(0)
            self._print(line)

    def _print(self, message):
        prefix = f"{self.color}[{self.name:<16}]{self.reset}"
        print(f"{prefix} {message}", flush=True)

    def is_alive(self):
        if self.process is None:
            return False
        return self.process.poll() is None

    def handle_exit(self):
        code = self.process.poll()
        if self.stopped_intentionally or self.stopped_by_toggle:
            self._print(f"stopped (exit code {code})")
            return

        tail_text = "\n".join(self._recent_lines)
        crash_type = _classify_crash(tail_text)
        self._print(f"CRASHED (exit code {code}) — classified as {crash_type}")

        if crash_type == "transient":
            # Protocol Lazarus: known-flaky errors (a mic device hiccup, a
            # dropped socket) get a near-instant retry and don't burn down
            # the restart budget, since they're expected to self-resolve.
            self.transient_restarts += 1
            self._print(f"transient error recognized ({tail_text.strip().splitlines()[-1][:80] if tail_text.strip() else code}) — "
                        f"instant restart #{self.transient_restarts}")
            time.sleep(self.TRANSIENT_RESTART_SECONDS)
            self.start()
            return

        if self.restarts >= self.MAX_RESTARTS:
            self._print(f"giving up after {self.MAX_RESTARTS} restarts — see {self.log_path}")
            return

        wait = self.BACKOFF_BASE_SECONDS * (2 ** self.restarts)
        self.restarts += 1
        self._print(f"restarting in {wait}s (attempt {self.restarts}/{self.MAX_RESTARTS})")
        time.sleep(wait)
        self.start()

    def toggle_disabled_stop(self):
        """Called by the Supervisor loop when this service's feature
        toggle gets flipped off in the control-center UI while it's
        running. Distinct from stop() (permanent shutdown) — this one
        expects to potentially be restarted if the toggle flips back on."""
        self.stopped_by_toggle = True
        if self.process and self.process.poll() is None:
            self._print("feature toggle turned off — stopping...")
            try:
                if os.name == "nt":
                    self.process.terminate()
                else:
                    self.process.send_signal(signal.SIGINT)
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def toggle_enabled_restart(self):
        """Called by the Supervisor loop when a previously toggle-stopped
        service's feature gets flipped back on."""
        self.stopped_by_toggle = False
        self._print("feature toggle turned back on — starting...")
        self.start()

    def stop(self):
        self.stopped_intentionally = True
        if self.process and self.process.poll() is None:
            self._print("stopping...")
            try:
                if os.name == "nt":
                    self.process.terminate()
                else:
                    self.process.send_signal(signal.SIGINT)
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self._log_file:
            self._log_file.close()


# ----------------------------------------------------------------------
# Supervisor loop
# ----------------------------------------------------------------------
class Supervisor:
    TOGGLE_POLL_INTERVAL_SECONDS = 5

    def __init__(self, services):
        self.services = services
        self._running = True

    def run(self):
        # Start everything. Services gated by a toggle that's currently
        # off will report False from start() but stay under supervision
        # (via toggle_key) so a live toggle flip can start them later.
        for svc in self.services:
            svc.start()

        supervised = [svc for svc in self.services if svc.is_alive() or svc.toggle_key]
        if not supervised:
            print("No services started — nothing to supervise. Exiting.")
            return

        active_count = len([s for s in supervised if s.is_alive()])
        print("\n" + "=" * 60)
        print(f" Argus supervisor running {active_count} service(s), watching {len(supervised)} for toggle changes. Ctrl+C to stop.")
        print("=" * 60 + "\n")

        last_toggle_poll = 0

        try:
            while self._running:
                now = time.time()

                # Crash handling for anything that died on its own.
                for svc in supervised:
                    if svc.process is not None and not svc.is_alive() and not svc.stopped_intentionally and not svc.stopped_by_toggle:
                        svc.handle_exit()

                # Live toggle polling (Protocol-toggle-aware services only).
                if now - last_toggle_poll >= self.TOGGLE_POLL_INTERVAL_SECONDS:
                    last_toggle_poll = now
                    for svc in supervised:
                        if not svc.toggle_key or svc.stopped_intentionally:
                            continue
                        enabled = svc._toggle_is_enabled()
                        if enabled and (svc.process is None or not svc.is_alive()) and svc.stopped_by_toggle:
                            svc.toggle_enabled_restart()
                        elif not enabled and svc.is_alive() and not svc.stopped_by_toggle:
                            svc.toggle_disabled_stop()

                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down all services...")
        finally:
            for svc in supervised:
                svc.stop()
            print("All services stopped.")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def print_service_list():
    print("\nCore modes (pick exactly one with --mode):")
    for key, info in CORE_SERVICES.items():
        print(f"  {key:<10} {info['script']:<20} {info['desc']}")
    print("\nWatchdogs (on by default, disable with --no-watchdogs):")
    for key, info in WATCHDOG_SERVICES.items():
        print(f"  {key:<10} {info['script']:<20} {info['desc']}")
    print("\nExtras (opt-in with --with, unless marked [toggle] -- those start")
    print("automatically based on their switch in the control-center UI):")
    for key, info in EXTRA_SERVICES.items():
        toggle_note = f"[toggle: {info['toggle_key']}]" if info.get("toggle_key") else ""
        print(f"  {key:<16} {info['script']:<22} {info['desc']} {toggle_note}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Argus unified launcher / process supervisor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", choices=list(CORE_SERVICES.keys()), default="remote",
                         help="Which core interaction mode to run (default: remote)")
    parser.add_argument("--no-watchdogs", action="store_true",
                         help="Don't start overwatch/security_warden/aegis/sentinel")
    parser.add_argument("--with", dest="extras", nargs="*", default=[],
                         choices=list(EXTRA_SERVICES.keys()),
                         help="Optional extra services to start alongside core")
    parser.add_argument("--minimal", action="store_true",
                         help="Only run the chosen core mode, nothing else")
    parser.add_argument("--list", action="store_true",
                         help="List all known services and exit")
    args = parser.parse_args()

    if args.list:
        print_service_list()
        return

    project_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(project_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    python_exe = sys.executable

    plan = [(args.mode, CORE_SERVICES[args.mode])]
    if not args.minimal:
        if not args.no_watchdogs:
            plan += list(WATCHDOG_SERVICES.items())
        # Explicitly requested extras...
        requested_extra_names = set(args.extras)
        # ...plus every toggle-aware extra, always — its own toggle state
        # (in feature_toggles.json, editable live from the control-center
        # UI) is what actually decides whether it runs. This is what makes
        # "flip the switch in the UI" able to start a brand-new background
        # service without needing to know to pass --with ahead of time.
        toggle_aware_names = {name for name, info in EXTRA_SERVICES.items() if info.get("toggle_key")}
        plan += [(name, EXTRA_SERVICES[name]) for name in (requested_extra_names | toggle_aware_names)]

    services = []
    for index, (name, info) in enumerate(plan):
        services.append(ManagedService(
            name=name,
            script=info["script"],
            desc=info["desc"],
            index=index,
            python_exe=python_exe,
            project_dir=project_dir,
            log_dir=log_dir,
            runner=info.get("runner"),
            toggle_key=info.get("toggle_key"),
        ))

    print("Argus Supervisor — services to launch:")
    for svc in services:
        print(f"  - {svc.name}: {svc.desc}")
    print(f"Logs will be written to: {log_dir}\n")

    Supervisor(services).run()


if __name__ == "__main__":
    main()
