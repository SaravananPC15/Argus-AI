"""
macro_deck.py — Protocol Virtual Terminal Extension (macro storage + validation).

DISTINCT FROM remote_server.py's EXISTING phone/browser control: that's
already a full freeform chat interface reachable from a phone
(remote_server.py's FastAPI uplink -- see radio_silence.py's own
docstring, which points at the same surface). This protocol is a
narrower, different one: a fixed grid of named one-tap buttons, each
bound to a specific (action, target) pair chosen ahead of time, not
freeform text. remote_server.py is EXTENDED (not duplicated) with a
/macros page and a couple of endpoints that import this module for
storage/validation and executor.run_local_command for execution -- the
exact same dispatcher the chat interface already uses, so a macro gets
the same feature-toggle checks, safety checks, and audit logging as
anything typed or spoken.

SECURITY, ON PURPOSE: a macro is an (action, target) pair chosen and
saved by YOU ahead of time, not arbitrary text/code sent from the phone
at tap time. add_macro() below validates `action` against
brain.VALID_ACTIONS -- the exact same allow-list brain.py's own NLU
router is constrained to -- so a macro button can never fire something
the router itself wouldn't be allowed to run. Every request to
/macros/* still goes through remote_server.py's existing gatekeeper MFA
middleware, same as every other route in that app.
"""

import json
import os

from brain import VALID_ACTIONS

MACROS_FILE = "macros.json"


def load_macros(path: str = MACROS_FILE) -> list:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def save_macros(macros: list, path: str = MACROS_FILE):
    with open(path, "w") as f:
        json.dump(macros, f, indent=2)


def add_macro(name: str, action: str, target: str, icon: str = "⚡", path: str = MACROS_FILE) -> dict:
    """Raises ValueError if `action` isn't a recognized action (see
    module docstring) or if `name` is already taken."""
    if action not in VALID_ACTIONS:
        raise ValueError(f"'{action}' isn't a recognized action -- refusing to save this macro. "
                          f"Valid actions: {sorted(VALID_ACTIONS)}")
    if not name or not name.strip():
        raise ValueError("Macro name can't be empty.")
    macros = load_macros(path)
    if any(m["name"] == name for m in macros):
        raise ValueError(f"A macro named '{name}' already exists.")
    macro = {"name": name, "action": action, "target": target, "icon": icon}
    macros.append(macro)
    save_macros(macros, path)
    return macro


def remove_macro(name: str, path: str = MACROS_FILE) -> bool:
    macros = load_macros(path)
    remaining = [m for m in macros if m["name"] != name]
    if len(remaining) == len(macros):
        return False
    save_macros(remaining, path)
    return True


def get_macro(name: str, path: str = MACROS_FILE):
    for m in load_macros(path):
        if m["name"] == name:
            return m
    return None


def run_macro(name: str, path: str = MACROS_FILE) -> str:
    """Looks up the macro and runs it through executor.run_local_command
    -- the SAME dispatcher every other action in this project goes
    through. Local import (not at module top) to avoid a circular
    import: executor.py imports this module (for the 'run_macro'
    action -- see executor.py), so this can't import executor.py back
    at load time, only when this function actually runs."""
    macro = get_macro(name, path)
    if macro is None:
        return f"No macro named '{name}'. Saved macros: {[m['name'] for m in load_macros(path)]}"
    from executor import run_local_command
    return run_local_command(macro["action"], macro["target"])


if __name__ == "__main__":
    import tempfile
    tmp_path = os.path.join(tempfile.gettempdir(), "argus_test_macros.json")
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    # 1. Valid macro saves fine.
    add_macro("morning routine", "system_command", "check status", path=tmp_path)
    assert get_macro("morning routine", path=tmp_path)["action"] == "system_command"
    print("[1/4] Valid macro saved and retrievable: OK")

    # 2. Invalid action is rejected BEFORE it ever reaches storage.
    try:
        add_macro("evil macro", "delete_everything", "target", path=tmp_path)
        raise AssertionError("should have rejected an unrecognized action")
    except ValueError as e:
        assert "not a recognized action" in str(e) or "isn't a recognized" in str(e)
    print("[2/4] Unrecognized action rejected at save time, not silently stored: OK")

    # 3. Duplicate name rejected.
    try:
        add_macro("morning routine", "open_app", "notepad", path=tmp_path)
        raise AssertionError("should have rejected a duplicate name")
    except ValueError:
        pass
    print("[3/4] Duplicate macro name rejected: OK")

    # 4. Remove works, and running a since-removed macro fails cleanly
    #    rather than crashing.
    assert remove_macro("morning routine", path=tmp_path) is True
    assert remove_macro("morning routine", path=tmp_path) is False  # already gone
    result = run_macro("morning routine", path=tmp_path)
    assert "No macro named" in result
    print("[4/4] Remove + running a missing macro fails cleanly: OK")

    os.remove(tmp_path)
    print("\nAll macro_deck self-tests passed.")
