"""
castellan.py — Protocol Castellan (Proximity Lock).

Watches for your phone's Bluetooth Low Energy advertisement via RSSI
scanning. When it hasn't been seen for a stretch (you walked away with
it), the workstation locks — same mechanism as executor.py's
"lock"/"secure" system_command, just triggered by distance instead of
your voice.

On the "walk back and it unlocks" half: this module wakes the display
and chimes when your phone comes back in range, but it deliberately does
NOT auto-type your Windows password to actually unlock the session. That
would mean storing your real login credential on disk in a
recoverable form and having a background process type it in — a much
bigger security downgrade than the convenience is worth. Windows itself
draws the same line: its own "Dynamic Lock" feature only locks on
distance, never auto-unlocks. So "walk back and it's ready for you"
(display on, chime, session still safely locked) is the honest version
of this feature.

Uses `bleak` for cross-platform BLE scanning.
"""

import asyncio
import time
import os
import sys
import json

STATE_FILE = "secure_vault/castellan_state.json"
RSSI_LOST_THRESHOLD_SECONDS = 25  # how long the phone can be "unseen" before we lock
SCAN_INTERVAL_SECONDS = 6


def _load_state():
    if not os.path.exists(STATE_FILE):
        return {"enrolled_mac": None}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"enrolled_mac": None}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def is_enrolled() -> bool:
    return bool(_load_state().get("enrolled_mac"))


async def scan_for_devices(timeout=6.0):
    """Returns a list of {"name", "address", "rssi"} for nearby BLE devices —
    used both for enrollment (pick your phone from the list) and monitoring."""
    from bleak import BleakScanner
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results = []
    for device, adv_data in devices.values():
        results.append({
            "name": device.name or "Unknown device",
            "address": device.address,
            "rssi": adv_data.rssi,
        })
    return sorted(results, key=lambda d: -d["rssi"])


def enroll_device(mac_address: str, device_name: str = ""):
    state = _load_state()
    state["enrolled_mac"] = mac_address
    state["enrolled_name"] = device_name
    _save_state(state)
    return f"Enrolled {device_name or mac_address} as your proximity key, macha."


def _lock_workstation():
    """Reuses the exact same cross-platform lock logic as executor.py's
    system_command handler, so behavior stays consistent."""
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.LockWorkStation()
    elif sys.platform == 'darwin':
        os.system("pmset displaysleepnow")
    else:
        os.system("loginctl lock-session 2>/dev/null || xdg-screensaver lock 2>/dev/null")


def _wake_display():
    """Best-effort 'wake up and get ready' on proximity return. Does not
    unlock the session — see module docstring."""
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.SetThreadExecutionState(0x80000002)  # ES_CONTINUOUS | ES_DISPLAY_REQUIRED
    elif sys.platform == 'darwin':
        os.system("caffeinate -u -t 1")
    # No universal equivalent on Linux without knowing the desktop environment.


async def _monitor_loop(on_lock=None, on_return=None):
    state = _load_state()
    enrolled_mac = state.get("enrolled_mac")
    if not enrolled_mac:
        print("[Castellan] No device enrolled yet. Call castellan.enroll_device() first.")
        return

    last_seen = time.time()
    is_currently_away = False

    print(f"[Castellan] Monitoring proximity for {state.get('enrolled_name', enrolled_mac)}...")
    while True:
        try:
            import feature_toggles
            if not feature_toggles.is_enabled("castellan"):
                await asyncio.sleep(SCAN_INTERVAL_SECONDS)
                continue
        except Exception:
            pass

        try:
            nearby = await scan_for_devices(timeout=SCAN_INTERVAL_SECONDS)
            seen_now = any(d["address"] == enrolled_mac for d in nearby)
        except Exception as e:
            print(f"[Castellan] Scan error: {e}")
            seen_now = True  # fail safe: don't lock the user out on a scan glitch

        if seen_now:
            last_seen = time.time()
            if is_currently_away:
                print("[Castellan] Device back in range. Waking display.")
                _wake_display()
                if on_return:
                    on_return()
                is_currently_away = False
        else:
            if not is_currently_away and (time.time() - last_seen) > RSSI_LOST_THRESHOLD_SECONDS:
                print("[Castellan] Device out of range. Locking workstation.")
                _lock_workstation()
                if on_lock:
                    on_lock()
                is_currently_away = True


def start_monitor(on_lock=None, on_return=None):
    """Blocking entry point — run this in its own thread/process."""
    asyncio.run(_monitor_loop(on_lock, on_return))


if __name__ == "__main__":
    if not is_enrolled():
        print("[Castellan] No device enrolled. Run enroll_device() first (see the control-center UI's Castellan panel).")
    else:
        start_monitor()
