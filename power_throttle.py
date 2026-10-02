"""
power_throttle.py — Protocol Smart Power Throttling.

DIFFERENT FROM aegis.py: aegis.py already watches battery/CPU and
SPEAKS A WARNING when they cross a threshold -- a passive alert. This
protocol ACTS on the battery state: when running on battery (not wall
power), it shrinks the token budget the fast model is asked to use and
gives every polling loop a multiplier to slow itself down by, then
restores normal behavior the instant a charger is reconnected. Same
starting point as aegis.py (psutil's battery reading), different job.

CROSS-PROCESS STATE: like feature_toggles.py, this persists its
current reading to a small JSON file (power_state.json) instead of an
in-memory variable, because this project's background services run as
separate processes (see launch.py) -- an in-memory flag in THIS
process wouldn't be visible to model_router.py running inside the main
Argus process, or to any other service's own loop.
"""

import json
import os
import threading
import time

import psutil

STATE_FILE = "power_state.json"
_lock = threading.Lock()

ON_BATTERY_TOKEN_MULTIPLIER = 0.5
ON_BATTERY_POLL_INTERVAL_MULTIPLIER = 2.0

LOW_BATTERY_PERCENT = 20
LOW_BATTERY_TOKEN_MULTIPLIER = 0.25
LOW_BATTERY_POLL_INTERVAL_MULTIPLIER = 4.0

MIN_TOKEN_FLOOR = 64  # never throttle a response down to something unusably short


def _default_state() -> dict:
    return {"on_battery": False, "percent": 100, "low_battery": False,
            "token_multiplier": 1.0, "poll_interval_multiplier": 1.0, "updated_at": None}


def read_power_state() -> dict:
    """What every OTHER module calls -- cheap (a small JSON file read),
    safe to call often, works from any process. Returns the 'plugged
    in, full power' default if run_monitor() hasn't run yet, or if this
    machine reports no battery at all (a desktop -- or this sandbox)."""
    if not os.path.exists(STATE_FILE):
        return _default_state()
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return _default_state()


def _compute_state() -> dict:
    battery = psutil.sensors_battery()
    if battery is None:
        state = _default_state()
        state["updated_at"] = time.time()
        return state

    on_battery = not battery.power_plugged
    low_battery = on_battery and battery.percent <= LOW_BATTERY_PERCENT

    if low_battery:
        token_mult, poll_mult = LOW_BATTERY_TOKEN_MULTIPLIER, LOW_BATTERY_POLL_INTERVAL_MULTIPLIER
    elif on_battery:
        token_mult, poll_mult = ON_BATTERY_TOKEN_MULTIPLIER, ON_BATTERY_POLL_INTERVAL_MULTIPLIER
    else:
        token_mult, poll_mult = 1.0, 1.0

    return {"on_battery": on_battery, "percent": battery.percent, "low_battery": low_battery,
            "token_multiplier": token_mult, "poll_interval_multiplier": poll_mult,
            "updated_at": time.time()}


def _write_state(state: dict, path: str = None):
    path = path or STATE_FILE  # resolved at CALL time, not def time -- see _self_test for why that matters
    with _lock:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f)
        os.replace(tmp_path, path)  # atomic on POSIX -- a reader never sees a half-written file


def scale_tokens(base_tokens: int) -> int:
    """model_router.py calls this when building a request -- see its
    select_model() integration."""
    state = read_power_state()
    return max(int(base_tokens * state["token_multiplier"]), MIN_TOKEN_FLOOR)


def scale_interval(base_seconds: float) -> float:
    """Any polling loop can opt into calling this to slow itself down
    on battery (not forced onto existing services in this pass -- see
    SETUP.md's scoping notes)."""
    state = read_power_state()
    return base_seconds * state["poll_interval_multiplier"]


def run_monitor(check_interval_seconds: int = 15):
    """Blocking loop: recomputes and persists the power state every
    check_interval_seconds. Run in its own thread/process, same as this
    project's other background services (see launch.py)."""
    print("[Power Throttle] Monitor started.")
    last_on_battery = None
    while True:
        state = _compute_state()
        _write_state(state)
        if state["on_battery"] != last_on_battery:
            mode = "battery" if state["on_battery"] else "wall power"
            print(f"[Power Throttle] Now on {mode} ({state['percent']}%) -- "
                  f"token budget x{state['token_multiplier']}, poll interval x{state['poll_interval_multiplier']}")
            last_on_battery = state["on_battery"]
        time.sleep(check_interval_seconds)


def _self_test():
    import tempfile
    global STATE_FILE
    real_state_file = STATE_FILE
    STATE_FILE = os.path.join(tempfile.gettempdir(), "argus_test_power_state.json")
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)

    try:
        # 1. No state file yet -> full-power default, no throttling.
        assert read_power_state()["token_multiplier"] == 1.0
        assert scale_tokens(1000) == 1000
        print("[1/4] Default (no state file yet) -> full power, no throttling: OK")

        # 2. This sandbox's actual battery reading -- informational, must not crash either way.
        computed = _compute_state()
        print(f"[2/4] _compute_state() on this machine: {computed} (no crash either way: OK)")

        # 3. Simulate on-battery: writer + reader round-trip, scale_tokens/scale_interval react.
        _write_state({"on_battery": True, "percent": 55, "low_battery": False,
                      "token_multiplier": ON_BATTERY_TOKEN_MULTIPLIER,
                      "poll_interval_multiplier": ON_BATTERY_POLL_INTERVAL_MULTIPLIER,
                      "updated_at": time.time()})
        assert scale_tokens(1000) == 500
        assert scale_interval(10.0) == 20.0
        print("[3/4] Simulated on-battery state -> tokens/interval scaled correctly: OK")

        # 4. Simulate low battery: more aggressive throttling, and the token floor holds
        #    even for a tiny base_tokens request.
        _write_state({"on_battery": True, "percent": 12, "low_battery": True,
                      "token_multiplier": LOW_BATTERY_TOKEN_MULTIPLIER,
                      "poll_interval_multiplier": LOW_BATTERY_POLL_INTERVAL_MULTIPLIER,
                      "updated_at": time.time()})
        assert scale_tokens(1000) == 250
        assert scale_tokens(100) == MIN_TOKEN_FLOOR  # 100 * 0.25 = 25, floor kicks in at 64
        assert scale_interval(15.0) == 60.0
        print("[4/4] Simulated low-battery state -> more aggressive throttling + token floor holds: OK")

        print("\nAll power_throttle self-tests passed.")
    finally:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        STATE_FILE = real_state_file


if __name__ == "__main__":
    _self_test()
