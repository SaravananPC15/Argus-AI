"""
acoustic_link.py — Protocol Acoustic Data Link.

Encodes a short text message as a sequence of near-ultrasonic audio
tones (FSK -- frequency-shift keying) that another device's microphone
can capture and decode, for the case where Wi-Fi is down but both
devices still have a speaker and a mic in the same room.

HONEST SCOPING: this is real, working FSK -- the same family of
technique behind old dial-up modem handshakes, DTMF touch-tones, and
consumer "audio QR code" libraries like Chirp/ggwave, not a novel
invention. The DSP core below (encode_message/decode_message) is
genuinely solid and is tested against itself as plain numpy arrays --
no hardware needed to verify the algorithm is correct, and
_self_test() at the bottom does exactly that, including with injected
noise and a random start offset. What CAN'T be verified without an
actual laptop and phone in an actual room is the acoustic part: real
speaker/microphone frequency response, ambient noise, and room
acoustics all affect range and reliability in ways a unit test can't
touch. Treat this as good for a few words across a quiet room, not a
wireless network replacement -- by design this runs at roughly
10 bits/second (short, robust symbols beat fast, fragile ones here).

"Near-ultrasonic" means symbol frequencies sit around 17-19kHz -- faint
to inaudible for most adults, but NOT inaudible to everyone in the room
(children, some younger adults, and most pets can hear it clearly).
Cheap laptop/phone speakers and mics also roll off in fidelity before
true ultrasonic (>20kHz) territory, which is why this stays just under
that line rather than trying to go fully ultrasonic.
"""

import numpy as np

SAMPLE_RATE = 44100
SYMBOL_DURATION = 0.1  # seconds/symbol -- slow, but robust to real-world noise
BASE_FREQ = 17000
FREQ_STEP = 125
NUM_SYMBOLS = 16  # 4 bits/symbol (one nibble)
PREAMBLE_FREQS = (16500, 16750)  # fixed sync tones, outside the data band


def _tone(freq: float, duration: float = SYMBOL_DURATION, sample_rate: int = SAMPLE_RATE,
          amplitude: float = 0.5) -> np.ndarray:
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    # Hann-windowed to avoid clicks at symbol boundaries, which would
    # otherwise smear energy across frequencies and make adjacent
    # symbols harder to tell apart.
    window = np.hanning(len(t))
    return amplitude * np.sin(2 * np.pi * freq * t) * window


def _symbol_freq(nibble: int) -> float:
    return BASE_FREQ + nibble * FREQ_STEP


def encode_message(text: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Returns a 1D float32 numpy array of audio samples: two preamble
    tones, then one length byte, the UTF-8 payload, and one XOR
    checksum byte, each byte as two FSK symbols (nibbles)."""
    payload = text.encode("utf-8")
    if len(payload) > 255:
        raise ValueError("acoustic_link is for short messages/alerts -- 255 bytes max")
    checksum = 0
    for b in payload:
        checksum ^= b
    full_payload = bytes([len(payload)]) + payload + bytes([checksum])

    tones = [_tone(f, sample_rate=sample_rate) for f in PREAMBLE_FREQS]
    for byte in full_payload:
        tones.append(_tone(_symbol_freq((byte >> 4) & 0xF), sample_rate=sample_rate))
        tones.append(_tone(_symbol_freq(byte & 0xF), sample_rate=sample_rate))
    return np.concatenate(tones).astype(np.float32)


def _dominant_freq(segment: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    windowed = segment * np.hanning(len(segment))
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(segment), d=1 / sample_rate)
    return float(freqs[np.argmax(spectrum)])


def _closest_symbol(freq: float) -> int:
    nibble = round((freq - BASE_FREQ) / FREQ_STEP)
    return max(0, min(NUM_SYMBOLS - 1, nibble))


def _find_preamble(audio: np.ndarray, sample_rate: int, symbol_len: int):
    """Slides a window across `audio` looking for the two preamble tones
    back-to-back. Quarter-symbol step size trades precision for speed --
    fine at this project's message lengths."""
    step = max(symbol_len // 4, 1)
    limit = max(len(audio) - 2 * symbol_len, 0)
    for start in range(0, limit + 1, step):
        seg1 = audio[start:start + symbol_len]
        seg2 = audio[start + symbol_len:start + 2 * symbol_len]
        if len(seg2) < symbol_len:
            break
        f1 = _dominant_freq(seg1, sample_rate)
        f2 = _dominant_freq(seg2, sample_rate)
        if abs(f1 - PREAMBLE_FREQS[0]) < FREQ_STEP / 2 and abs(f2 - PREAMBLE_FREQS[1]) < FREQ_STEP / 2:
            return start
    return None


def decode_message(audio: np.ndarray, sample_rate: int = SAMPLE_RATE):
    """Best-effort decode of a captured audio buffer. Returns
    (text_or_None, ok: bool) -- ok=False means sync wasn't found, the
    capture ended early, or the checksum didn't match (any of which
    just means "try again" -- there's no partial-credit here by design,
    a wrong decode is worse than a clear failure for anything driving
    an action)."""
    symbol_len = int(sample_rate * SYMBOL_DURATION)
    sync_start = _find_preamble(audio, sample_rate, symbol_len)
    if sync_start is None:
        return None, False

    pos = sync_start + 2 * symbol_len
    nibbles = []
    declared_length, total_nibbles_needed = None, None
    while pos + symbol_len <= len(audio):
        freq = _dominant_freq(audio[pos:pos + symbol_len], sample_rate)
        nibbles.append(_closest_symbol(freq))
        pos += symbol_len

        if len(nibbles) == 2 and declared_length is None:
            declared_length = (nibbles[0] << 4) | nibbles[1]
            total_nibbles_needed = (1 + declared_length + 1) * 2

        if total_nibbles_needed is not None and len(nibbles) >= total_nibbles_needed:
            break

    if declared_length is None or total_nibbles_needed is None or len(nibbles) < total_nibbles_needed:
        return None, False

    byte_values = [(nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles) - 1, 2)]
    length_byte = byte_values[0]
    payload_bytes = bytes(byte_values[1:1 + length_byte])
    if len(byte_values) <= 1 + length_byte:
        return None, False
    received_checksum = byte_values[1 + length_byte]

    computed_checksum = 0
    for b in payload_bytes:
        computed_checksum ^= b

    try:
        text = payload_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None, False
    return text, received_checksum == computed_checksum


# ---------------------------------------------------------------------
# Hardware I/O -- thin wrappers, deliberately kept separate from the
# DSP core above so the algorithm can be fully unit-tested without a
# real microphone/speaker (see _self_test at the bottom). Needs
# `sounddevice` (PortAudio) installed on the machine actually running
# Argus -- see requirements.txt.
# ---------------------------------------------------------------------

def send_over_speaker(text: str):
    import sounddevice as sd
    audio = encode_message(text)
    sd.play(audio, samplerate=SAMPLE_RATE)
    sd.wait()


def listen_and_decode(listen_seconds: float = 10.0):
    import sounddevice as sd
    recording = sd.rec(int(listen_seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                        channels=1, dtype="float32")
    sd.wait()
    return decode_message(recording.flatten())


def _self_test():
    rng = np.random.default_rng(0)
    messages = ["hi", "ARGUS: build finished", "battery low", ""]

    print("--- clean round-trip ---")
    for msg in messages:
        audio = encode_message(msg)
        decoded, ok = decode_message(audio)
        status = "OK" if (ok and decoded == msg) else "MISMATCH"
        print(f"  [{status}] {msg!r} -> {decoded!r} (checksum ok: {ok})")
        assert ok and decoded == msg, f"round-trip failed for {msg!r}"

    print("--- with leading silence (simulates late mic start) + light noise ---")
    for msg in ("delayed hello",):
        audio = encode_message(msg)
        padded = np.concatenate([np.zeros(int(0.37 * SAMPLE_RATE), dtype=np.float32), audio])
        noisy = padded + rng.normal(0, 0.02, size=padded.shape).astype(np.float32)
        decoded, ok = decode_message(noisy)
        status = "OK" if (ok and decoded == msg) else "MISMATCH"
        print(f"  [{status}] {msg!r} -> {decoded!r} (checksum ok: {ok})")
        assert ok and decoded == msg, "round-trip failed with offset + noise"

    print("--- garbage audio (no message present) correctly reports failure, not a wrong guess ---")
    garbage = rng.normal(0, 0.1, size=int(2 * SAMPLE_RATE)).astype(np.float32)
    decoded, ok = decode_message(garbage)
    print(f"  decoded={decoded!r} ok={ok}")
    assert decoded is None and ok is False

    print("\nAll acoustic_link DSP self-tests passed.")


if __name__ == "__main__":
    _self_test()
