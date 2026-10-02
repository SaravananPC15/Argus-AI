#!/usr/bin/env python3
"""
gesture_control_service.py — launch.py entry point for Protocol Zero-G
Visual Controls.

gesture_control.py is the library (decision logic + camera loop);
launch.py runs standalone scripts as subprocesses, so this is the thin
runnable wrapper, same pattern as castellan.py/radio_silence.py's own
__main__ blocks. Maps each recognized gesture to a concrete local
effect via executor.run_local_command, reusing the existing
system_command handling rather than reimplementing OS calls here.
"""
import gesture_control
from executor import run_local_command

_ACTION_DISPATCH = {
    "stop_media": lambda: run_local_command("system_command", "stop media playback"),
    "pause_media": lambda: run_local_command("system_command", "pause media playback"),
    "clear_terminal": lambda: run_local_command("system_command", "clear terminal"),
    "screenshot": lambda: run_local_command("system_command", "take a screenshot"),
}


def on_gesture(action: str):
    handler = _ACTION_DISPATCH.get(action)
    if handler:
        result = handler()
        print(f"[Gesture Control] {action} -> {result}")


if __name__ == "__main__":
    gesture_control.run_gesture_loop(on_gesture)
