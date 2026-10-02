"""
self_dev_daemon.py — Standalone runner for self_dev.py's periodic cycle.

A thin wrapper so the Self-Development Engine can be supervised by
launch.py the same way overwatch.py/aegis.py/security_warden.py are —
one process, one job, auto-restarted on crash. All the actual logic
(diagnosis, patch drafting, the human-approval gate) lives in self_dev.py;
this file is just the "run it forever, on an interval" loop.
"""

import time
import self_dev

CYCLE_INTERVAL_SECONDS = 60 * 20  # every 20 minutes


def main():
    print("[Self-Dev Daemon] Watching Argus's own codebase for issues to propose fixes for...")
    print("[Self-Dev Daemon] Nothing is ever auto-applied — proposals wait in the Log History panel for your approval.")
    while True:
        try:
            self_dev.run_cycle()
        except Exception as e:
            print(f"[Self-Dev Daemon] Cycle error: {e}")
        time.sleep(CYCLE_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
