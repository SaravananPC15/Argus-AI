"""
gesture_control.py — Protocol Zero-G Visual Controls.

Watches the webcam locally (via MediaPipe) for a small set of hand
gestures and fires the mapped action -- close a terminal, pause media,
clear the screen -- without touching the keyboard.

HONEST SCOPING ON THE LIBRARY VERSION: MediaPipe deprecated its old
`mp.solutions.hands` API (the one nearly every older tutorial uses) in
favor of the Tasks API (`mediapipe.tasks.python.vision`). Verified
directly against the mediapipe package while building this (0.10.x):
`mp.solutions` no longer exists at all -- only the Tasks API does. This
file is written against that current API on purpose; code copied from
an older tutorial using `mp.solutions.hands` will not run on a current
MediaPipe install. Every class/method/signature this file calls
(GestureRecognizer, BaseOptions, GestureRecognizerOptions,
recognize_for_video, mp.Image/ImageFormat) was checked against the
installed package's actual signatures, not written from memory alone.

MediaPipe's GestureRecognizer task ships with a small set of
pre-trained built-in gestures (Open_Palm, Closed_Fist, Thumb_Up,
Thumb_Down, Victory, Pointing_Up, ILoveYou) -- "Open_Palm" is
effectively the "stop sign" gesture, already trained and included,
rather than something to hand-roll from raw landmark coordinates.

REQUIRES A DOWNLOADED MODEL FILE the Tasks API needs explicitly (unlike
the old solutions API, which bundled its model internally) -- see
SETUP.md for the one-time download command. Also requires an actual
webcam. Because of that, the gesture-to-action decision logic (the part
that actually matters and can go wrong -- cooldowns, mapping) is
factored out into pick_action() below and unit-tested against a faked
recognizer result; the camera capture loop around it is carefully
written against verified signatures but, unlike most of this project's
other new modules, could not be run end-to-end in the environment this
was built in.
"""

import time

MODEL_PATH = "models/gesture_recognizer.task"

# Maps MediaPipe's built-in gesture categories to actions this project
# already exposes -- extend this mapping, don't hand-roll new gesture
# DETECTION; the recognizer's built-in categories are the vocabulary.
GESTURE_ACTIONS = {
    "Open_Palm": "stop_media",     # the brief's "stop sign"
    "Closed_Fist": "pause_media",
    "Thumb_Down": "clear_terminal",
    "Victory": "screenshot",
}

COOLDOWN_SECONDS = 1.5  # minimum time between repeated triggers of the SAME gesture
MIN_CONFIDENCE = 0.6


def pick_action(top_gesture_name: str, confidence: float, last_fired: dict, now: float = None):
    """Pure decision logic, separated from the camera/recognizer loop so
    it's testable without either: given the top recognized gesture this
    frame (or None if no hand/gesture was seen), decides whether to
    fire a mapped action, respecting MIN_CONFIDENCE and per-gesture
    COOLDOWN_SECONDS debouncing so a gesture held for two seconds fires
    once, not dozens of times. Mutates and returns `last_fired`
    (gesture_name -> last-fired timestamp) alongside the action."""
    now = time.time() if now is None else now
    if not top_gesture_name or confidence < MIN_CONFIDENCE:
        return None, last_fired

    action = GESTURE_ACTIONS.get(top_gesture_name)
    if action is None:
        return None, last_fired

    if now - last_fired.get(top_gesture_name, 0) < COOLDOWN_SECONDS:
        return None, last_fired

    last_fired[top_gesture_name] = now
    return action, last_fired


def _build_recognizer(model_path: str = MODEL_PATH):
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    base_options = mp_python.BaseOptions(model_asset_path=model_path)
    options = mp_vision.GestureRecognizerOptions(
        base_options=base_options,
        running_mode=mp_vision.RunningMode.VIDEO,
        num_hands=1,
    )
    return mp_vision.GestureRecognizer.create_from_options(options)


def run_gesture_loop(on_gesture, model_path: str = MODEL_PATH, camera_index: int = 0):
    """Blocking loop: opens the webcam, runs the recognizer per frame,
    calls on_gesture(action_name) whenever pick_action() says to fire.
    Run in its own thread/process, same as this project's other
    background services (see launch.py)."""
    import cv2
    import mediapipe as mp

    recognizer = _build_recognizer(model_path)
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {camera_index}.")

    last_fired = {}
    print("[Gesture Control] Watching webcam for mapped gestures.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.1)
                continue

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            result = recognizer.recognize_for_video(mp_image, int(time.time() * 1000))

            top_name, confidence = None, 0.0
            if result.gestures and result.gestures[0]:
                top = result.gestures[0][0]
                top_name, confidence = top.category_name, top.score

            action, last_fired = pick_action(top_name, confidence, last_fired)
            if action:
                on_gesture(action)
    finally:
        cap.release()
        recognizer.close()


def _self_test():
    fired = []
    last_fired = {}
    t = 1000.0

    # Below-confidence detection: correctly ignored.
    action, last_fired = pick_action("Open_Palm", 0.3, last_fired, now=t)
    assert action is None
    print("[1/4] Low-confidence detection ignored: OK")

    # First confident Open_Palm: fires.
    action, last_fired = pick_action("Open_Palm", 0.9, last_fired, now=t)
    assert action == "stop_media"
    fired.append((t, action))
    print("[2/4] First confident gesture fires the mapped action: OK")

    # Same gesture, 0.5s later (inside cooldown): must NOT re-fire.
    action, last_fired = pick_action("Open_Palm", 0.9, last_fired, now=t + 0.5)
    assert action is None
    print("[3/4] Held gesture inside cooldown window does not re-fire: OK")

    # Same gesture, after COOLDOWN_SECONDS: fires again.
    action, last_fired = pick_action("Open_Palm", 0.9, last_fired, now=t + COOLDOWN_SECONDS + 0.1)
    assert action == "stop_media"
    print("[4/4] Same gesture after cooldown elapses fires again: OK")

    # Unmapped gesture (e.g. "Pointing_Up" isn't in GESTURE_ACTIONS): no crash, no action.
    action, _ = pick_action("Pointing_Up", 0.95, {}, now=t)
    assert action is None

    print("\nAll gesture_control decision-logic self-tests passed.")
    print("(Camera/recognizer loop itself needs real hardware + the downloaded model file -- "
          "see SETUP.md -- and could not be exercised here.)")


if __name__ == "__main__":
    _self_test()
