# Argus

A local, offline-first personal AI assistant built on Ollama — 46 protocols
covering voice, system control, developer tooling, security, and remote
phone access. Runs on modest hardware (built and tuned against an 8GB RAM
laptop, no GPU required for the core system).

Full setup, architecture notes, and honest scoping decisions for every
protocol are in **[SETUP.md](SETUP.md)** — start there. This file only
covers the one thing that trips people up on a fresh clone: two model
files aren't in this repo.

## What's not included, and why

Two features depend on pretrained model weights that are excluded here
(`.gitignore`) because they're large binaries that don't belong in git
history, not because they're difficult to get:

| File | Used by | Size |
|---|---|---|
| `pretrained_models/spkrec-ecapa-voxceleb/` | `voice_id.py` (speaker verification) | ~85MB |
| `yolov8n.pt` | `vision_stream.py` (object detection) | ~6MB |

## You don't need to manually download either one

Checked directly against the code, not assumed: both libraries fetch
their own weights automatically the first time that specific feature
actually runs.

- **Voice ID**: `voice_id.py` calls SpeechBrain's `EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", savedir="pretrained_models/spkrec-ecapa-voxceleb")` — the first time voice enrollment runs, SpeechBrain downloads the model from Hugging Face into that folder on its own.
- **Vision**: `vision_stream.py` calls `YOLO('yolov8n.pt')` — Ultralytics' library downloads the official weights automatically the first time it's instantiated, if the file isn't already present.

**The only real requirement: have internet access the first time you use
voice enrollment or vision/camera features specifically.** Everything
else in Argus works fully offline, same as always — this is the one
narrow exception, and only on first use per model.

If you'd rather pre-fetch them yourself before running anything (e.g. to
confirm they downloaded correctly, or on a machine you know will be
offline later):

```bash
# Voice ID model (~85MB)
python -c "from speechbrain.inference.speaker import EncoderClassifier; EncoderClassifier.from_hparams(source='speechbrain/spkrec-ecapa-voxceleb', savedir='pretrained_models/spkrec-ecapa-voxceleb')"

# YOLOv8n weights (~6MB) -- running this line downloads it into the current directory
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
```

Both require `pip install -r requirements.txt` to have already run
(`speechbrain` and `ultralytics` are both listed there).

## Everything else

`pip install -r requirements.txt`, then see **SETUP.md** for the full
walkthrough — VS Code setup, every protocol's configuration steps, and
the security/privacy reasoning behind each one that adds new capability.
