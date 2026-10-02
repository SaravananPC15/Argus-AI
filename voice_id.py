"""
voice_id.py — Feature 7: Voice-based user recognition.

The project already bundles speechbrain's spkrec-ecapa-voxceleb model
under pretrained_models/ but nothing used it. This wires it up: Argus
can enroll one "owner" voiceprint, then compare any future utterance
against it. wake_agent.py / hands.py use this to gate risky actions
(system_command, git_push, run_script, recycle bin) so only the
enrolled owner's voice can trigger them — anyone else gets a polite
"only my primary user can do that."

This is a convenience/access-control layer, not a security boundary —
voice similarity scoring can be spoofed. Treat it the same way you'd
treat a house key, not a bank vault.
"""

import os
import numpy as np

VOICEPRINT_FILE = "secure_vault/owner_voiceprint.npy"
SIMILARITY_THRESHOLD = 0.68  # cosine similarity; tune based on your mic/room

_classifier = None  # lazy-loaded singleton, since loading the model takes a moment


def _get_classifier():
    global _classifier
    if _classifier is None:
        from speechbrain.inference.speaker import EncoderClassifier
        _classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir="pretrained_models/spkrec-ecapa-voxceleb",
        )
    return _classifier


def _embed(audio_path: str):
    classifier = _get_classifier()
    signal = classifier.load_audio(audio_path)
    embedding = classifier.encode_batch(signal.unsqueeze(0))
    return embedding.squeeze().detach().cpu().numpy()


def is_enrolled() -> bool:
    return os.path.exists(VOICEPRINT_FILE)


def enroll_owner(audio_path: str) -> str:
    """Records the primary user's voiceprint from a sample clip (ideally
    5-10 seconds of clear, natural speech)."""
    try:
        embedding = _embed(audio_path)
        os.makedirs(os.path.dirname(VOICEPRINT_FILE), exist_ok=True)
        np.save(VOICEPRINT_FILE, embedding)
        return "Voiceprint enrolled. I'll recognize you from now on, macha."
    except Exception as e:
        print(f"[Voice ID Error] Enrollment failed: {e}")
        return "Enrollment failed — check that the audio sample is valid and speechbrain is installed."


def is_owner(audio_path: str, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """Compares an utterance's voiceprint against the enrolled owner.
    Returns True if the "voice_id" toggle is off, or if there's no
    enrolled owner yet (fail-open, so a fresh install isn't locked out
    of its own risky actions until the user explicitly enrolls) —
    enroll_owner() + the UI toggle are what turn the gate on."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("voice_id"):
            return True
    except Exception:
        pass

    if not is_enrolled():
        return True

    try:
        owner_embedding = np.load(VOICEPRINT_FILE)
        sample_embedding = _embed(audio_path)

        cosine_similarity = np.dot(owner_embedding, sample_embedding) / (
            np.linalg.norm(owner_embedding) * np.linalg.norm(sample_embedding)
        )
        return cosine_similarity >= threshold
    except Exception as e:
        print(f"[Voice ID Error] Verification failed: {e}")
        # Fail open rather than locking the legitimate owner out over a
        # transient audio/model error — safety.py's confirmation gate is
        # still the backstop for risky actions either way.
        return True
