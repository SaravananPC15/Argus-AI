# Argus Architecture

Argus is organized around a small set of core responsibilities rather than one giant script. The system is designed to be modular and local-first, with multiple entry points that feed into a central reasoning layer.

## 1. High-Level Architecture

```text
                           ┌───────────────────────┐
                           │   User Interaction    │
                           │  Voice / Browser /    │
                           │  Terminal / Phone     │
                           └──────────┬────────────┘
                                      │
                                      ▼
                           ┌───────────────────────┐
                           │   Entry Points        │
                           │ main.py               │
                           │ wake_agent.py         │
                           │ remote_server.py      │
                           │ launch.py             │
                           └──────────┬────────────┘
                                      │
                                      ▼
                           ┌───────────────────────┐
                           │   brain.py            │
                           │  Central Router       │
                           │  Action Dispatch      │
                           └──────────┬────────────┘
                                      │
                 ┌────────────────────┼────────────────────┐
                 │                    │                    │
                 ▼                    ▼                    ▼
        ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
        │  ears.py      │    │  voice.py     │    │  tools /      │
        │ voice input   │    │ TTS / audio   │    │ executor.py   │
        └───────┬───────┘    └───────┬───────┘    └───────┬───────┘
                │                    │                    │
                └────────────────────┼────────────────────┘
                                     ▼
                        ┌───────────────────────┐
                        │  Local Execution      │
                        │  scripts / browser    │
                        │  git / file actions   │
                        └──────────┬────────────┘
                                   │
                                   ▼
                        ┌───────────────────────┐
                        │ Local Storage         │
                        │ sqlite / FAISS /      │
                        │ audio_cache / docs    │
                        └───────────────────────┘
```

## 2. Main Layers

### Entry Layer
This is the interface layer where the user interacts with the assistant.

Examples:
- `main.py` — legacy microphone loop
- `wake_agent.py` — local wake-word or clap-driven assistant
- `remote_server.py` — browser or phone interface
- `launch.py` — supervisor that manages the main stack and watchdogs

### Routing Layer
The routing brain decides what the user wants and which capability should handle it.

Responsibilities:
- classify the intent
- route actions such as research, chat, git, vision, or script execution
- preserve memory and context
- decide whether to use a fast local model or deeper reasoning

### Execution Layer
This is where actual actions happen:

- run local scripts
- open apps
- read or write files
- perform browser automation
- trigger remote control features
- run git operations
- contact local services and background tasks

### Storage Layer
Argus stores:

- conversational memory
- semantic embeddings for retrieval
- logs and audit history
- local documents or knowledge base
- cached media and generated outputs

Important local pieces include:
- `audio_cache/`
- `documents/`
- `argus_vault.db`
- `argus_conversations.faiss`

### Monitoring / Safety Layer
Argus has watchdogs and safety monitors that watch over the system while it runs.

Examples:
- `overwatch.py`
- `security_warden.py`
- `aegis.py`
- `sentinel.py`
- `launch.py` process supervision

These help keep the agent operational, safe, and recoverable.

## 3. Why the Architecture Is Modular

Argus is designed as a collection of independent functions rather than one monolithic loop.

This gives it several benefits:

- easier debugging
- safer rollout of new protocols
- ability to disable or enable protocol groups selectively
- better local resilience when a service fails
- simple remote web UI integration

## 4. Key Design Principles

### Local-first
The default behavior is to stay on the local machine and avoid unnecessary cloud dependency.

### Privacy-conscious
Sensitive actions are verified and logged. Local storage keeps user data under direct control.

### Runtime safety
Argus is designed to confirm high-risk actions before they execute.

### Incremental capability growth
New features are added as protocol modules, not by expanding a single giant function.

## 5. Flow of a Typical Request

A typical user command flows like this:

1. User speaks, types, or triggers the remote dashboard.
2. Entry point receives the message.
3. `brain.py` interprets the request.
4. The router decides among:
   - chat
   - research
   - workflow planning
   - file action
   - browser action
   - system automation
   - remote control
5. `executor.py` or a specialized module performs the action.
6. Result is returned to the user.
7. Relevant results are stored in memory and logs.

## 6. Background Services and Watchdogs

Argus is not only an interactive AI assistant. It also runs background services to support its workflows.

Examples:
- voice or wake events
- phone/web dashboard updates
- notifications and audit output
- schedule or automation tasks
- security scans
- crash recovery and restarts

These background services keep the assistant more autonomous and resilient.

## 7. Protocol Grouping

The repo organizes capabilities into protocol families so it remains understandable:

- Voice & Control
- Intelligence & Memory
- Research & Planning
- Vision & Perception
- Security & Privacy
- Remote Access
- Automation & Workflow
- Monitoring
- Developer Tools

This makes the project easier to reason about and easier to extend.

## 8. Why This Matters for Discoverability

For a project like Argus, architecture clarity matters because the audience is not only developers: it includes builders, researchers, privacy-minded users, and people exploring local AI assistants.

A clean architecture helps show:

- what the project actually does
- how it differs from a simple chatbot
- why it is valuable beyond a demo
- how it stays modular and extensible

---

This repo is at its best when you think of it as a local AI operating environment, not just a single script with one command.

