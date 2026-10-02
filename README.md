# 🤖 Argus — 29+ Protocol Local AI Assistant

> **No cloud. No tracking. Pure local intelligence running on your machine.**

A modular, local-first personal AI assistant built on **Ollama** featuring multi-agent orchestration, voice control, computer vision, autonomous workflows, and 29+ specialized protocols. Everything runs offline on modest hardware (tested on 8GB RAM, no GPU required).

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Open Source](https://img.shields.io/badge/Open%20Source-Yes-brightgreen.svg)](https://github.com/SaravananPC15/Argus-AI)
[![Status](https://img.shields.io/badge/Status-Active%20Development-success.svg)](#)

---

## 🚀 Quick Start

```bash
# Clone & setup
git clone https://github.com/SaravananPC15/Argus-AI.git
cd Argus-AI

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Install & run Ollama
ollama pull llama3.2:1b llama3.2 llama3.1 moondream qwen2.5:0.5b

# Launch Argus
python launch.py                    # Full stack with watchdogs
python launch.py --mode wake        # Clap-activated voice assistant
python launch.py --mode legacy      # Simple mic loop (legacy)
```

**Full setup guide:** See [SETUP.md](SETUP.md) for detailed instructions, VS Code configuration, and protocol setup.

---

## ✨ Key Features

### 🎤 Voice & Control
- **Clap-to-activate** voice assistant with wake-word detection
- **Phone/browser remote control** via LAN or Tailscale (VPN)
- **Whisper speech-to-text** + local TTS (Silero)
- **Speaker ID verification** (gates risky voice actions)

### 🧠 Intelligent Reasoning
- **Multi-agent council** — 8 specialist personas debate complex problems
- **Semantic long-term memory** — recalls relevant conversations from history
- **Model routing by complexity** — fast 1B model for chat, larger models for research
- **Autonomous workflow planning** — multi-step task orchestration with checkpointing

### 👁️ Vision & Perception
- **Real-time object detection** (YOLOv8, room awareness)
- **Webcam streaming** with on-screen HUD overlay
- **Gesture control** — hand gestures recognized and mapped to actions

### 🛠️ Developer & System Tools
- **Git automation** — commit, push, and branch operations via voice
- **Script execution** with sandboxing (Docker/restricted subprocess)
- **File operations** — read, write, organize documents
- **Browser automation** — web scraping, form filling, screenshot capture
- **Calendar & email agents** — manage your schedule and inbox

### 🔐 Security & Privacy
- **Local-first architecture** — 99% of operations never leave your machine
- **Voice-based confirmation** for risky actions (git push, system lock, etc.)
- **Audit logging** — every action tracked in local database
- **MFA gatekeeper** — OTP-protected dashboard login
- **Network anomaly detection** — monitors suspicious activity

### 📊 Autonomous Monitoring
- **Overwatch** — network anomaly detector
- **Security Warden** — vault file-tamper monitor
- **Aegis** — CPU/battery health monitor
- **Sentinel** — Python syntax error detector (real-time)
- **Protocol Lazarus** — crash recovery with intelligent restart budgeting

---

## 🎯 29+ Protocols

| Category | Protocols |
|---|---|
| **Voice & Control** | Clap Detection, Wake Word, Radio Silence, Smart Dictation |
| **Intelligence** | Round Table (Multi-Agent), Model Routing, Semantic Memory, Conversation Recall |
| **Reasoning** | Frontier Escalation, Deep Research, Autonomous Workflows, Multi-Turn Checkpointing |
| **Vision** | Room Awareness, Object Detection, Gesture Control, Webcam Streaming |
| **Security** | Voice ID, Safety Confirmation, Audit Logging, MFA Gatekeeper, Castellan (Bluetooth Proximity) |
| **System** | Git Archeologist, Dataset Synthesis, Script Sandbox, Smart Power Throttling |
| **Monitoring** | Lazarus (Self-Healing), Network Anomaly Detection, File Tamper Monitor, Battery Health |
| **Developer** | Auto-Documentation, Syntax Guardian, Big-O Complexity Auditor, Database Indexing Optimizer |
| **Integration** | MCP Tool Bridge (Model Context Protocol), Peer-to-Peer Graph Sync, Off-Peak Data Harvesting |
| **UX** | No Slop Filter, Mind Map Exporter, Macro Deck, Virtual Terminal, Acoustic Data Link |
| **Remote Access** | Remote Cursor Control, Screen Mirror, Wireless Launcher, Tailscale VPN Ready |

**Full protocol reference:** See [PROTOCOLS.md](PROTOCOLS.md)

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────┐
│          ENTRY POINTS                          │
│  main.py (legacy) | wake_agent.py (local) |    │
│  remote_server.py (phone/browser)              │
└────────────────┬────────────────────────────────┘
                 │
        ┌────────▼────────┐
        │   brain.py      │
        │  (Router)       │
        └────────┬────────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
┌───▼──┐  ┌──────▼──────┐  ┌─▼────────┐
│ ears │  │   brain     │  │  hands   │
│voice │  │ Ollama LLM  │  │executor  │
└──────┘  │  reasoning  │  └──────────┘
          └─────────────┘
               │
    ┌──────────┴──────────┐
    │                     │
┌───▼─────┐        ┌──────▼──────┐
│ FAISS   │        │ Local DB    │
│  RAG    │        │  (sqlite)   │
└─────────┘        └─────────────┘
```

**Full architecture details:** See [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 📱 Remote Control

### Phone Dashboard (Web UI)
Access from any device on your network:
```
http://<your-laptop-ip>:8000
```

**Features:**
- Real-time chat with streaming responses
- Full-screen cursor control (touch-drag to move cursor)
- Macro deck (saved voice command buttons)
- Audit log viewer
- Model selector
- Feature toggles

### Wireless Launcher
Start Argus from your phone (PIN-protected):
```
1. Install the PWA: http://<laptop-ip>:8765
2. Enter your PIN
3. Laptop starts remotely
```

### Reach Argus Anywhere
Use **Tailscale** (free, VPN) to access your laptop from anywhere:
```bash
# Install on both devices, sign in to same account
# Use Tailscale IP instead of local IP in dashboard URL
```

See [SETUP.md § 17](SETUP.md#17-reaching-argus-from-anywhere-not-just-your-home-wifi) for details.

---

## 📚 Documentation

- **[SETUP.md](SETUP.md)** — Complete installation & configuration guide
- **[PROTOCOLS.md](PROTOCOLS.md)** — All 29+ protocols explained
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — System design & data flow
- **[EXAMPLES.md](EXAMPLES.md)** — Voice command samples & use cases
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — How to contribute

---

## 🔧 Customization

### Voice Commands
Edit the routing prompt in `brain.py` (search "CRITICAL EXAMPLES") to add new commands or modify behavior.

### Protocols & Features
Toggle protocols on/off in the control center:
```python
python -c "import feature_toggles; feature_toggles.set_enabled('protocol_name', True)"
```

### Models
Change LLM models or use different ones:
```python
# In model_router.py or round_table.py
AGENT_MODEL_OVERRIDES = {
    'llama3.1': 'your-custom-model'
}
```

---

## 💾 Storage & Privacy

All data stored locally:
- **`audio_cache/`** — Voice transcripts, audio files
- **`documents/`** — Uploaded PDFs for RAG
- **`argus_vault.db`** — Audit logs, conversation history
- **`argus_conversations.faiss`** — Semantic memory index
- **`argus_calendar.json`** — Calendar events (no account needed)

**Nothing leaves your machine** except:
- Optional **Frontier Escalation** (cloud LLM, opt-in only, requires confirmation + API key)
- Optional **Peer-to-Peer Graph Sync** (LAN-only by default, Tailscale-compatible)

---

## 🎯 Use Cases

- **Personal assistant** — Calendar, email, reminders
- **Developer workflow** — Git automation, code analysis, documentation generation
- **Research & learning** — Deep research, multi-agent debates, knowledge synthesis
- **Content creation** — Markdown generation, mind mapping, structured notes
- **System automation** — Script execution, monitoring, alerts
- **Privacy-first AI** — No telemetry, no accounts, no tracking

---

## 🛡️ Security Model

### Confirmation for Risky Actions
Commands like `git_push`, `run_script`, lock/shutdown require verbal confirmation.

### Voice-Based Authorization
Speaker verification prevents unauthorized voice commands (optional, needs enrollment).

### Audit Trail
Every action logged with timestamp, source, and result in `argus_vault.db`.

### Restricted Execution
Scripts run in a sandbox (Docker if available, otherwise restricted subprocess with CPU/memory limits).

### MFA for Remote Access
Dashboard login requires OTP if enabled (disabled by default; **enable if accessing over untrusted network**).

---

## 📊 Hardware Requirements

- **CPU:** Any modern processor (tested on Intel i5/i7, M1 Mac)
- **RAM:** 8GB minimum (tested on 8GB; 16GB+ recommended for better concurrency)
- **GPU:** Not required (all models run on CPU)
- **Disk:** ~20GB for models + data
- **Microphone:** Required for voice features (any USB mic works)
- **Webcam:** Optional (needed for vision/room awareness)

---

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repo
2. Create a feature branch
3. Test thoroughly (especially protocols)
4. Submit a PR with a clear description

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

Free for personal and commercial use. Attribution appreciated but not required.

---

## 🌟 Show Your Support

If Argus helps you, please:
- ⭐ **Star the repo** (helps with discoverability)
- 🐛 **Report issues** if you find bugs
- 💡 **Share feature requests** via GitHub Discussions
- 📢 **Spread the word** on social media

---

## 🔗 Links

- **GitHub:** https://github.com/SaravananPC15/Argus-AI
- **Issues:** https://github.com/SaravananPC15/Argus-AI/issues
- **Discussions:** https://github.com/SaravananPC15/Argus-AI/discussions
- **Author:** [@SaravananPC15](https://github.com/SaravananPC15)

---

## 📝 Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and updates.

---

## ⚠️ Model Files Not Included

Two large model files are auto-downloaded on first use (no manual action needed):

| Model | Used by | Size | Auto-download |
|---|---|---|---|
| `pretrained_models/spkrec-ecapa-voxceleb/` | Voice ID (speaker verification) | ~85MB | ✅ First voice ID usage |
| `yolov8n.pt` | Vision (object detection) | ~6MB | ✅ First vision/camera usage |

**Internet required only on first use of these specific features.** All other features work completely offline.

---

**Built with ❤️ for privacy, automation, and local intelligence.**
