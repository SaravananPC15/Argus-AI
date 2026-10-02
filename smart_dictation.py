"""
smart_dictation.py — Protocol Smart Dictation (Global Audio Input Override).

Registers a global hotkey (default: Ctrl+Alt+D) that works anywhere in
the OS, not just inside Argus. Press it, speak, press it again (or just
pause) — Whisper transcribes it, and the text gets typed directly into
whatever field your cursor is in, via the same pyautogui trick
executor.py's ghost_type already uses.

Platform notes:
- Windows/Linux: the `keyboard` library needs to run with sufficiently
  elevated permissions to register a truly global hook; on Linux this
  usually means running as root or being in the `input` group.
- macOS: global key listening additionally requires granting Accessibility
  permissions to your terminal/Python in System Settings.
"""

import threading
import time
import os
import wave
import pyaudio
import pyautogui
import keyboard

from voice_engine import whisper_model
import feature_toggles

HOTKEY = "ctrl+alt+d"
RATE = 16000
CHUNK = 1024
CHANNELS = 1
FORMAT = pyaudio.paInt16
MAX_RECORD_SECONDS = 12

_recording = False
_p = None


def _record_until_release(hotkey_combo):
    """Records audio while the hotkey is held, OR for MAX_RECORD_SECONDS
    if using a toggle-style single press (simpler, more reliable across
    platforms than tracking key-up events for a combo)."""
    global _p
    if _p is None:
        _p = pyaudio.PyAudio()

    stream = _p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    frames = []
    print("[Smart Dictation] Recording... press the hotkey again or wait to stop.")

    start = time.time()
    stop_flag = threading.Event()

    def wait_for_second_press():
        keyboard.wait(HOTKEY)
        stop_flag.set()

    listener = threading.Thread(target=wait_for_second_press, daemon=True)
    listener.start()

    while not stop_flag.is_set() and (time.time() - start) < MAX_RECORD_SECONDS:
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)

    stream.stop_stream()
    stream.close()

    output_path = "audio_cache/dictation_slice.wav"
    os.makedirs("audio_cache", exist_ok=True)
    wf = wave.open(output_path, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(_p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()
    return output_path


def _on_hotkey():
    global _recording
    if not feature_toggles.is_enabled("smart_dictation"):
        return
    if _recording:
        return  # a second press is handled by the listener thread inside _record_until_release
    _recording = True
    try:
        audio_path = _record_until_release(HOTKEY)
        print("[Smart Dictation] Transcribing...")
        text = whisper_model.transcribe(audio_path, fp16=False)["text"].strip()
        if text:
            print(f"[Smart Dictation] Typing: {text}")
            # Small delay so the hotkey's own key-up events don't get
            # captured as part of the typed text.
            time.sleep(0.3)
            pyautogui.write(text, interval=0.01)
    except Exception as e:
        print(f"[Smart Dictation Error]: {e}")
    finally:
        _recording = False


def start_listener():
    """Blocking entry point — run this in its own thread/process."""
    print(f"[Smart Dictation] Listening for hotkey: {HOTKEY} (press once to start, again to stop)")
    keyboard.add_hotkey(HOTKEY, _on_hotkey)
    keyboard.wait()  # blocks forever, dispatching hotkey callbacks


if __name__ == "__main__":
    start_listener()
