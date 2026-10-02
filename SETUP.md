# Argus — Setup Notes

> **If you got this as a fresh download alongside your existing project
> folder:** this delivery deliberately leaves out `pretrained_models/`
> (the ~85MB speaker-ID model) and `yolov8n.pt` (~6MB, vision) — those
> weren't touched, and you already have them from your own upload. Copy
> everything from this zip INTO your existing project folder (overwrite
> the code files) rather than replacing the whole folder, so those two
> stay put. `voice_id.py` and `vision_stream.py` will fail without them.

This is a personal AI-assistant project built from many independent scripts
("microservices") that talk to each other through local files (`audio_cache/`)
and a local database, rather than one single "start everything" entry point.
Read this before you try to run it in VS Code.

## 0. Opening and running this in VS Code

1. **Open the folder** — VS Code → File → Open Folder... → select this
   project's root folder (the one with `main.py`, `requirements.txt`,
   this `SETUP.md` in it).
2. **Install the Python extension** (Microsoft's `ms-python.python`) if
   you don't already have it — VS Code will usually prompt you to when
   it notices the `.py` files.
3. **Create and select a virtual environment** (recommended, keeps this
   project's dependencies separate from anything else on your machine):
   ```bash
   python -m venv .venv
   ```
   Then `Ctrl+Shift+P` (`Cmd+Shift+P` on macOS) → "Python: Select
   Interpreter" → pick the `.venv` one VS Code just found.
4. **Open an integrated terminal** — `` Ctrl+` `` (backtick) — it should
   already be using `.venv` if you selected it in step 3 (you'll see
   `(.venv)` at the start of the prompt).
5. Follow section 3 onward below (install dependencies, install Ollama,
   run it) — every command in this doc is meant to be typed into that
   same integrated terminal.
6. To actually run something, either use that terminal (`python
   remote_server.py`, `python launch.py`, etc.) or open the file and hit
   VS Code's ▷ "Run" button — both do the same thing.

The rest of this document (sections 1-11) covers what was fixed, how the
project is structured, and everything you need installed — read on.

## 1. What actually got fixed

- `main.py`, `dashboard.py`, `test_text.py` were calling `brain.process_command()`
  (an `async` function) without `await`/`asyncio.run()`. Fixed — they now run it
  correctly through `asyncio`.
- `hands.py` imported a function (`automate_browser`) that didn't exist in
  `browser_agent.py` (the real name is `execute_browser_automation`), and would
  have raised an `ImportError` the moment the `browser_control` action was hit.
  Fixed, and it's now correctly awaited via `asyncio.run()`.
- `hands.py`'s action list only covered about half of the actions `brain.py`
  can actually route to (it was missing `vision_task`, `room_awareness`,
  `run_script`, `read_file`, `deep_research`, `read_clipboard`, `ghost_type`,
  `connect_app`, `schedule_task`, `git_push`). It now delegates those to
  `executor.py`'s `run_local_command`, the same logic `wake_agent.py` and
  `remote_server.py` already use, so behavior is consistent across every
  entry point.
- `research_agent.py` used the deprecated `duckduckgo_search` package while
  `search_engine.py` used its replacement, `ddgs`. Both now use `ddgs`.

`test_bug.py` was left untouched — it's a scratch file that intentionally
divides by zero and isn't imported by anything else. Delete it if you don't
need it.

## 2. Two generations of the same assistant, in one folder

- **Legacy path** (mic loop + local TTS): `main.py` → `ears.py` / `voice.py` →
  `brain.py` → `hands.py`. Simple, but limited to the older action set.
- **Current path** (clap + wake-word, or phone/web uplink): `wake_agent.py` or
  `remote_server.py` → `brain.py` → `executor.py`, using Whisper + Silero TTS
  via `voice_engine.py`. This is the actively developed path and supports the
  full action set (vision, scheduling, git automation, research, etc.).

If you only want one working assistant, `wake_agent.py` (local, clap-triggered)
or `remote_server.py` (FastAPI server + web/phone UI) are the ones to run.

## 3. Install Python dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

`pyaudio` requires PortAudio at the OS level first:
- Windows: usually installs fine via pip directly.
- macOS: `brew install portaudio` before `pip install pyaudio`.
- Linux: `sudo apt install portaudio19-dev` before `pip install pyaudio`.

## 4. Install and start Ollama

The project talks to a **local Ollama server** for all LLM calls. Install it
from https://ollama.com, then pull the models this codebase actually calls:

```bash
ollama pull llama3.2:1b
ollama pull llama3.2
ollama pull llama3.1
ollama pull moondream
ollama pull qwen2.5:0.5b
```

(`qwen2.5:0.5b` is pulled by `download_model.py` — run
`python download_model.py` once if you want that model too, though nothing
else in the codebase currently calls it by name.)

## 5. Platform requirements — this project is Windows-first, with fallbacks

Several files call Windows-only APIs. Each now has a guarded macOS/Linux
fallback rather than crashing outright, but the fallback is a lesser
substitute in every case:
- `executor.py` — lock workstation: `pmset displaysleepnow` on macOS (sleeps
  the display, not a true lock), `loginctl`/`xdg-screensaver` on Linux.
- `tactical_hud.py` — the true win32 click-through trick has no equivalent;
  non-Windows gets a semi-transparent window that still captures clicks.
- `wake_agent.py` — `winsound.Beep` falls back to a terminal bell; audio
  playback falls back to `afplay` (macOS) / `aplay` (Linux).
- `hands.py` — recycle-bin emptying only works on Windows (`winshell`); on
  other platforms it tells you so instead of crashing.
- `executor.py` — network check now uses the right `ping` flag (`-n` vs `-c`)
  per platform automatically.
- `AppOpener` and `pywhatkit` are still built primarily for Windows
  app-launching; `open_app` has basic macOS/Linux equivalents for a few
  common apps but isn't as complete as the Windows path.

If you're on macOS/Linux, the rest of the codebase (LLM routing, RAG, web
search, FastAPI server, calendar, email) is fully portable.

## 6. Hardware / local resources needed

- A working microphone (`ears.py`, `wake_agent.py`, `remote_server.py`)
- A webcam if you want `vision_stream.py` / `room_awareness` (YOLOv8 —
  `yolov8n.pt` is already bundled in the project)
- `pretrained_models/spkrec-ecapa-voxceleb/` (already bundled) is used for
  speaker-recognition style tasks if you wire that in later.

## 7. Recommended: run everything with the unified launcher

Instead of opening 4-6 terminals by hand, use `launch.py` — it starts the
core assistant plus the background watchdogs as managed subprocesses, tags
and colors their output, restarts anything that crashes, writes per-service
logs to `./logs/`, and shuts everything down cleanly on Ctrl+C.

This is also **Protocol Lazarus**: crashes get classified as "transient"
(a flaky mic device, a dropped socket — near-instant retry, doesn't burn
down the restart budget) or "unknown" (real bugs — normal exponential
backoff, capped at 5 attempts so a genuinely broken service doesn't spin
forever). And every toggle-driven protocol (Castellan, Radio Silence,
Smart Dictation, RSS Aggregator, the Self-Development Engine) is watched
live — flip its switch on in the control-center UI and the launcher starts
it within a few seconds, no restart needed; flip it off and it stops.

```bash
python launch.py                        # remote_server.py + all watchdogs
python launch.py --mode wake            # wake_agent.py instead of remote_server
python launch.py --mode legacy          # main.py, the simple mic-loop version
python launch.py --minimal              # only the chosen core mode, nothing else
python launch.py --no-watchdogs         # core mode without background monitors
python launch.py --with vision_stream forge   # add optional extras
python launch.py --list                 # show every known service and exit
```

Only pick **one** `--mode` at a time — `remote` and `wake` both want the
microphone, and running them together will conflict.

## 8. Manual run order (if you'd rather not use the launcher)

**Legacy, simplest:**
```bash
python main.py
```

**Current, local clap+wake-word:**
```bash
python wake_agent.py
```

**Current, phone/web uplink:**
```bash
python remote_server.py
# then open http://<your-computer-ip>:8000 on your phone/browser
```

**Optional background services** (run each in its own terminal, only if you
want that feature):
```bash
python overwatch.py         # network anomaly monitor
python security_warden.py   # vault file-tamper monitor
python aegis.py             # CPU/battery health monitor
python sentinel.py          # watches your .py files for syntax errors as you save
python forge.py             # auto-sorts files dropped into ./Argus_Inbox
python vision_stream.py     # webcam object detection feed for room_awareness
python tactical_hud.py      # on-screen transparent overlay (Windows only)
python gesture_control_service.py     # Protocol Zero-G Visual Controls (needs the model file, see section 11)
python power_throttle_service.py      # Protocol Smart Power Throttling
python off_peak_harvester_service.py  # Protocol Off-Peak Data Harvesting (needs harvest_targets.json, see section 11)
python graph_sync_service.py          # Protocol Peer-to-Peer Graph Sync (needs ARGUS_GRAPH_SYNC_PASSPHRASE, see section 11)
```

## 9. New features added in this pass

Twelve upgrades were added on top of the bug fixes above (the unified
launcher in section 7 and the cross-platform fallbacks in section 5 are two
of them). Most of the rest work with zero extra config; two need a one-time
setup step:

- **Streaming replies** — casual chat now streams token-by-token instead of
  waiting for the full reply, over both the websocket voice path and a new
  `/command_stream` SSE endpoint, and in the dashboard's chat tab.

- **Semantic long-term memory** (`conversation_memory.py`) — every logged
  dialogue turn is now also embedded into a second FAISS index
  (`argus_conversations.faiss`), so Argus can recall relevant older
  conversations, not just the last 6 turns or explicit "remember that" facts.

- **Confirmation for risky actions** (`safety.py`) — `git_push`, `run_script`,
  emptying the recycle bin, and system commands like lock/shutdown/restart
  now require a spoken/typed "confirm" before they execute, across every
  entry point (voice loop, wake word, dashboard, remote server).

- **Proactive notifications** (`notifier.py`) — `overwatch.py`,
  `security_warden.py`, and `aegis.py` now push alerts to
  `audio_cache/alerts_outbox.jsonl`; `remote_server.py` broadcasts them to
  every connected websocket client, and the dashboard sidebar shows the
  latest ones.

- **Multi-turn workflow checkpointing** — `agent_orchestrator.py`'s
  autonomous workflows can now pause mid-plan with a clarifying question
  (saved to `audio_cache/workflow_checkpoint.json`) and resume once you
  answer, instead of failing or guessing.

- **Voice-based user recognition** (`voice_id.py`) — uses the bundled
  speechbrain ECAPA model to gate risky actions to your voice specifically.
  **Setup required to activate:**
  ```bash
  python -c "import voice_id; print(voice_id.enroll_owner('path/to/a_clear_10s_recording.wav'))"
  ```
  Until you enroll, this fails open (everyone is treated as the owner) —
  `safety.py`'s confirmation prompts are still the backstop either way.

- **Calendar & email** (`calendar_agent.py`, `email_agent.py`) — ask Argus
  things like "what's on my calendar tomorrow" or "add a dentist appointment
  Friday at 3pm" (stored locally in `argus_calendar.json`, no account
  needed). Email needs **one-time setup**:
  ```bash
  export ARGUS_SMTP_USER="you@gmail.com"
  export ARGUS_SMTP_PASSWORD="an app password, not your real password"
  ```
  Until these are set, "send an email" requests will tell you they're not configured.

- **Model routing by complexity** (`model_router.py`) — casual chat and
  quick classification use the fast `llama3.2:1b`; RAG synthesis, workflow
  planning/reporting, and deep research now use the larger `llama3.1` for
  better quality on tasks that benefit from it.

- **Document library web UI** — visit `http://<your-ip>:8000/library` (or
  the "Document Library" tab in the Streamlit dashboard) to upload PDFs and
  see everything currently ingested into the RAG index, instead of only
  being able to drop files into `documents/` blind.

- **Audit log** (`audit.py`) — every action Argus executes (across every
  entry point) is now logged to `argus_vault.db`'s `action_logs` table.
  View it at `http://<your-ip>:8000/audit` or the "Audit Log" tab in the
  dashboard.

## 10. The Control Center + 16 new Protocols

`remote_server.py`'s `/` page is now a full control center: a toggle switch
for every feature in this project (grouped by category), a model
selector (auto-routing or pick one manually), and a "Log History" panel
(top-right, the document icon) showing every self-diagnosis/patch
proposal and the full audit trail. Flipping a toggle takes effect
immediately — including starting/stopping background services that
`launch.py` supervises, live, without restarting anything.

**Three scoping decisions**, so behavior isn't a surprise:
- **Protocol Castellan** locks your workstation when your phone walks out
  of Bluetooth range (exactly what Windows' own "Dynamic Lock" does), but
  does **not** auto-type your password to unlock when you return — it
  wakes the display and leaves the actual unlock to you (Hello/PIN/etc).
  Storing a recoverable OS password on disk for a background process to
  type in is a real security downgrade for a small convenience gain.
- **Protocol Scraping Vanguard** fetches public pages politely
  (robots.txt-respecting, rate-limited) rather than doing fingerprint/
  proxy-rotation tricks to evade a platform's anti-bot systems. Give it
  specific public URLs (dataset repos, academic pages) rather than a bare
  topic — it won't guess at scraping a social platform directly.
- **The Self-Development Engine never auto-applies anything.** It
  diagnoses its own code (same checks used to build this project),
  drafts a fix, and puts it in the Log History panel for you to Approve
  or Reject — same pattern as Dependabot/Renovate opening a PR instead of
  merging to main. This matters more here than usual, since this
  codebase can already run shell commands and push to git.

### Setup required for two protocols

- **Voice ID** (gates risky voice actions to your voice) and **Protocol
  Castellan** (Bluetooth proximity) both start disabled and need
  enrollment once turned on:
  ```bash
  python -c "import voice_id; print(voice_id.enroll_owner('path/to/a_clear_10s_recording.wav'))"
  ```
  Castellan enrollment happens from the UI — flip its toggle on and it'll
  offer to scan for your phone.
- **Protocol Gatekeeper** (MFA on new-IP dashboard logins) delivers its
  code to the console running `remote_server.py` and to any already-connected
  device; wiring real SMS delivery would need your own Twilio-style
  credentials, which aren't fabricated here — see `gatekeeper.py`'s docstring.

### Everything else, by protocol

| Protocol | What it needs | Runs via |
|---|---|---|
| Git Archeologist | nothing | on-demand ("show me the commit history for X") |
| Dataset Synth | nothing | on-demand ("generate 5000 rows of...") |
| Multi-Agent Council | nothing | on-demand ("have the council debate...") |
| Lazarus (self-healing) | nothing | always, via `launch.py`'s Supervisor |
| Radio Silence | nothing (auto-generates a token on first run, printed to console) | background service, `nc <ip> 7777` |
| Smart Dictation | OS Accessibility permission on macOS; may need elevated perms on Linux | background service, `Ctrl+Alt+D` |
| Syntax Guardian | `autopep8`/`pycodestyle` (in requirements.txt) | automatic before every Protocol Shadow push |
| Smart Log Digest | nothing | on-demand ("give me today's summary") |
| Mind Map Exporter | nothing (starts empty, fills in as you use other protocols) | on-demand ("export the mind map") |
| Synthetic Anchor | nothing (put notes in a `notes/` folder to include them) | on-demand ("search my own notes for...") |
| RSS Aggregator | nothing (edit `DEFAULT_FEEDS` in `rss_aggregator.py` to change feeds) | background service |
| Auto-Documentation | nothing (never overwrites your original file) | on-demand ("add docstrings to X") |
| Mirage Cam | a webcam at index 0 | toggle in the console's action row |

Full command reference for every new action is in `brain.py`'s routing
prompt (search for "CRITICAL EXAMPLES") if you want to see exactly what
phrasing triggers what.

## 11. Protocol Round Table + 13 more protocols (this pass)

### The headline feature: a real multi-agent system, not just two personas

**Protocol Round Table** (`round_table.py`) generalizes **Multi-Agent
Council**'s two-persona debate (still there, unchanged, for a quick
design back-and-forth) into a full roster of eight specialists —
Architect, Debugger, Security Analyst, Data Engineer, Systems Engineer,
Researcher, Tutor, Pragmatist. It runs in exactly two situations,
matching how it was asked for:

1. **You assign it directly** — "convene the round table on X" / "get the
   team on this" — which always runs, auto-picking 2-4 relevant
   specialists for X.
2. **`agent_orchestrator.py` decides a task is complex enough on its
   own** — before planning an autonomous workflow, it now checks whether
   the objective is genuinely multi-domain (via the same relevance
   scoring used to pick specialists — see below) and, only if so,
   convenes the table first and feeds its verdict into the planner as
   extra context. A single-domain ask never comes close to the
   threshold and this adds nothing to the normal path.

Agent selection isn't a keyword match — the task and each specialist's
blurb are embedded (reusing the same sentence-transformer already
loaded for RAG, so this is free) and scored with real tiled attention
(`tiled_attention.py` — see below) as the query against the roster as
keys. The same distribution's entropy is the complexity signal that
decides #2 above.

**On "add all types of AI model, each an expert in its field":** every
specialist is a distinct *persona* (system prompt), not a separately
loaded multi-GB model — see `round_table.py`'s own docstring for why,
given this project's 8GB RAM budget (the same reasoning `model_router.py`
already uses for its FAST/REASONING split). Point any specialist at a
real model you've pulled via `AGENT_MODEL_OVERRIDES` in `round_table.py`
if your hardware supports keeping more than one loaded at once.

### Scoping decisions, so behavior isn't a surprise

A few of the 13 requested protocols needed a translation from the pitch
to something technically real. Same spirit as section 10's three
scoping decisions — quietly building the honest version and documenting
it, not silently doing less than asked:

- **Flash-Attention Emulation** (`tiled_attention.py`) cannot and does
  not speed up Argus's actual replies. Every `ollama.chat(...)` call in
  this codebase runs inside the separate Ollama server process (its own
  optimized llama.cpp/ggml backend) — this Python process never performs
  the model's own matrix math, so nothing here can accelerate it. What's
  real: the actual FlashAttention algorithm (online-softmax tiling,
  bounding peak memory instead of materializing a full score matrix),
  correctly implemented and benchmarked honestly — run
  `python tiled_attention.py --benchmark` and you'll see tiling is
  usually *not* faster at small scale, only more memory-bounded. It's
  what Round Table's agent-relevance scoring actually uses.
- **Shadow Sandbox Execution** (`sandbox.py`), now wired into `run_script`
  everywhere: Docker (used automatically if installed and its daemon is
  reachable) is real isolation. The automatic fallback — a restricted
  subprocess with a scratch temp dir, a timeout, and CPU/memory limits
  via `resource` on Linux/macOS — is meaningfully safer than a bare
  subprocess call but is **not** a security boundary against genuinely
  adversarial code (it shares the OS kernel and your user account). Good
  for catching an infinite loop or a typo'd `rm -rf`; not a substitute
  for not running code you don't trust.
- **Virtual Terminal Extension** (`macro_deck.py` + `remote_server.py`'s
  `/macros` page): a macro is an (action, target) pair *you* choose and
  save ahead of time, validated against the exact same action allow-list
  `brain.py`'s own router is constrained to (`brain.VALID_ACTIONS`) — the
  phone UI can tap a saved button, it can't smuggle new commands through.
  Every `/macros/*` request still passes through the existing Gatekeeper
  MFA middleware, same as every other route.
- **Acoustic Data Link** (`acoustic_link.py`) is real, working FSK — not
  a metaphor — but it's ~10 bits/second by design and the tones (17-19kHz)
  are quiet-to-inaudible for most adults, **not inaudible to everyone**
  (kids, some younger adults, and most pets can hear it). Good for a
  short alert across a quiet room, not a network replacement.
- **Peer-to-Peer Graph Sync** (`graph_sync.py`) means devices on the
  *same local network*, not internet-wide P2P, and "device" currently
  means "anything that can run this Python file" — there's no
  standalone phone app in this project, so a second phone needs Termux
  (Android) to actually participate as a peer, not just browse the
  chat UI.
- **Off-Peak Data Harvesting** (`off_peak_harvester.py`) draws the exact
  same line Scraping Vanguard already does — public pages you configure,
  robots.txt-respecting, no login/paywall/CAPTCHA bypassing. It adds
  autonomous scheduling and real headless-browser rendering (Playwright,
  for pages that need JS) on top of Scraping Vanguard's existing fetch,
  it doesn't duplicate it.

### Setup required for four protocols

- **Zero-G Visual Controls** needs a downloaded model file (MediaPipe's
  Tasks API doesn't bundle one, unlike the old deprecated `solutions`
  API):
  ```bash
  mkdir -p models
  curl -L -o models/gesture_recognizer.task \
    https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task
  ```
  Built-in gestures: Open_Palm (stop), Closed_Fist (pause), Thumb_Down
  (clear terminal), Victory (screenshot) — remap in `gesture_control.py`'s
  `GESTURE_ACTIONS`.
- **Peer-to-Peer Graph Sync** needs the same shared passphrase set on
  every device before anything will sync:
  ```bash
  export ARGUS_GRAPH_SYNC_PASSPHRASE="something long and not guessable"
  ```
- **Off-Peak Data Harvesting** starts with zero configured targets on
  purpose:
  ```bash
  python -c "import off_peak_harvester as h; h.add_target('https://example.com/feed.xml')"
  ```
- **Database Indexing Optimizer** defaults to report-only. It'll tell you
  the `CREATE INDEX` it would run; nothing is actually created unless you
  call `db_index_optimizer.optimize_database(..., apply=True)` yourself.

### Everything else, by protocol

| Protocol | What it needs | Runs via |
|---|---|---|
| Round Table | nothing | on-demand ("round table on X") + auto, complex tasks only |
| Semantic Context Compaction | nothing | automatic, internal (`context_compactor.py`) |
| Dynamic Sequence Sharding | nothing | on-demand ("this log file is huge, tell me...") |
| Big-O Complexity Auditor | nothing | on-demand ("what's the time complexity of X") |
| Database Indexing Optimizer | nothing (report-only by default) | on-demand ("check my database for slow queries") |
| Relational-to-NoSQL Transpiler | nothing | on-demand ("convert this schema to MongoDB") |
| Smart Power Throttling | nothing | background service, `power_throttle_service.py` |

Full command reference for every new action from this pass, including
the two MCP Bridge actions added just after it (below), is in
`brain.py`'s routing prompt (search for "CRITICAL EXAMPLES").

## 12. Protocol MCP Tool Bridge — built private, on purpose

This connects Argus to [Model Context Protocol](https://modelcontextprotocol.io)
tool servers — the standard now used across the industry for giving an
LLM structured access to things like a filesystem, a database, or
GitHub — instead of hand-writing a bespoke integration module for every
new external capability.

**You asked for this to stay private and single-user, so here's exactly
how that's enforced, not just claimed:**

1. **Argus is an MCP *client* only.** It reaches OUT to tool servers it
   starts itself. Nothing in this protocol makes Argus reachable BY
   anything else — there is no MCP *server* code here at all.
2. **stdio transport only — no network transport implemented.** MCP
   supports both local servers (a subprocess talking over stdin/stdout
   pipes, no socket involved) and remote servers (a real network
   endpoint). `mcp_bridge.py` only implements the local kind. Every
   server it talks to is a process running under your own OS account.
3. **`mcp_servers.json` starts empty.** Zero servers are pre-configured.
   Nothing connects to anything until you add it yourself, by name.
4. **Credentials live in your shell environment, never in a file this
   project tracks.** `mcp_servers.json` records which environment
   variable NAME a server reads (e.g. `GITHUB_TOKEN`), never the value.
5. **Off by default**, same as every other protocol that adds new
   connectivity.

### Setup

```bash
pip install mcp
python -c "import feature_toggles; feature_toggles.set_enabled('mcp_bridge', True)"

# Example: the official filesystem server, scoped to one folder only
python -c "
import mcp_bridge
mcp_bridge.add_server('filesystem', 'npx',
    ['-y', '@modelcontextprotocol/server-filesystem', '/home/you/documents'])
"

# Discover what it exposes, then use it
# (voice/text): "list my MCP tools"
# (voice/text): "use the filesystem tool to read notes.txt"
```

A tool whose name or description contains a destructive-sounding word
(delete, drop, purge, force, etc. — see `_RISKY_WORDS` in
`mcp_bridge.py`) is blocked until you say the word "confirmed" — this
is a trip-wire, not a substitute for reading what a server you add
can actually do before you add it.

### Honest limitation

Every other protocol in this project was tested by actually running it
— the log digest, the sandbox killing a real infinite loop, graph sync
over a real socket. This one is different: the `mcp` package and a live
MCP server weren't available in the environment this was built in, so
the actual protocol handshake in `connect_and_list_tools()`/
`call_tool()` was written carefully against the SDK's documented API
but could **not** be run end-to-end before delivery. What was tested —
config handling, the risky-tool safety check, and the full dispatch
logic against a mocked server — is in `mcp_bridge.py`'s own
`_self_test()`. Run it (`python mcp_bridge.py`) to see exactly what
that covers. Before you point this at anything you'd mind getting
wrong, add one real server and try `mcp_list_tools` yourself first.

## 13. Protocol Remote Cursor Control — full-screen phone view + touch drag

Clicking the screen-view button on the phone now opens a genuine
full-screen mirror of the laptop (not the small inline preview it used
to), with a visible cursor you drag with your finger — touch and drag
moves the real cursor, a quick tap clicks, a two-finger tap right-clicks.

**Read this before turning it on:** this is a materially bigger
capability than watching the screen — it lets whoever's holding the
phone actually operate the laptop. It has its own toggle
(`remote_cursor_control`, off by default) separate from `screen_feed`
(which stays toggle-free and view-only, as it always was). Turning this
on is a real decision, not a formality.

**Directly relevant to that decision:** `gatekeeper_mfa` — the OTP
check that gates the whole dashboard — also **defaults to off** in
this project, independent of anything built today. If this laptop is
ever on a network you don't fully trust (a shared flat, a campus
network, a coffee shop), turn `gatekeeper_mfa` on before you turn
`remote_cursor_control` on. Doing the second without the first means
anyone who can reach the dashboard's URL can drive your laptop with no
login at all. This isn't a bug introduced by this feature, but this
feature is exactly what makes it worth fixing before you rely on it.

### How the coordinate mapping works

The phone doesn't need to know the laptop's real screen resolution.
Touches are converted to a **normalized fraction** (0.0–1.0) of the
*displayed image*, accounting for letterboxing when the phone's aspect
ratio doesn't match the laptop's — sent over `/ws/cursor`, the server
multiplies by `pyautogui.size()` to get real pixel coordinates. Tested
directly (not just reasoned about): the letterbox math in both portrait
and landscape orientations, clamping for touches in the letterboxed
black bars, and exact corner/center mapping — all in
`/tmp/test_coords.js`-style checks during development; the actual
dispatch logic (move/click/double-click, malformed-message handling,
out-of-range clamping) was tested against a mocked `pyautogui`; and a
real `playwright` touchscreen simulation confirmed the on-screen cursor
actually moves in response to a real touch event, not just synthetic
function calls. What could **not** be tested here: the real end-to-end
path through an actual FastAPI server, actual websocket, and actual
`pyautogui` moving an actual cursor — that needs the real laptop.

### Setup

```bash
pip install pyautogui   # already a dependency for other protocols, listed once in requirements.txt
python -c "import feature_toggles; feature_toggles.set_enabled('remote_cursor_control', True)"
```

Then from the phone: tap the screen-view button — it now opens
full-screen directly, connects `/ws/cursor` automatically, and shows
"cursor control connected" at the bottom once it's live. If it instead
says "view-only," the toggle above isn't on yet.

## 14. Protocol Wireless Launcher — start Argus from your phone

A phone app (installable to your home screen) that starts Argus on
the laptop remotely: enter a PIN, it authenticates to the laptop over
the local network, and `launch.py --mode remote` starts up.

### Why this needs a SEPARATE always-on piece, not just remote_server.py

If Argus isn't running, `remote_server.py` isn't listening — there's
nothing for a phone to talk to. `launcher_listener.py` is a second,
deliberately tiny process (imports only `fastapi`/`uvicorn`/stdlib —
no `ollama`, no `torch`, no `faiss`) whose only job is to sit there
waiting for an authenticated "start" request. Run it via Windows Task
Scheduler at login so it's live whenever the laptop is on, independent
of whether the rest of Argus is.

### The security model

- **The PIN never leaves your phone, and the laptop never sees it.**
  The phone app encrypts the real password locally (AES-GCM, key
  derived from your PIN via PBKDF2, Web Crypto API) and stores only
  that ciphertext. A wrong PIN simply fails to decrypt — no network
  request happens at all.
- **The password never crosses the network either.** Once the PIN
  decrypts it locally, the phone proves it holds the correct password
  via an HMAC challenge-response against a single-use nonce
  (`/challenge` then `/start`) — verified byte-for-byte between
  Python and a real browser's Web Crypto API before this shipped, not
  just assumed to interoperate.
- **The toggle fails closed, not open.** Every other new protocol's
  toggle check fails *open* on an unreadable config (a typo shouldn't
  silently disable an ordinary chat action). This one is the deliberate
  exception: it launches a process, so an unreadable toggle file
  refuses instead of allowing it.
- **Rate-limited**: 5 failed attempts from one IP locks that IP out for
  5 minutes.
- Every attempt — accepted or rejected — goes through `audit.py`.

### What a phone web app genuinely cannot do

Being direct about a real platform limitation rather than glossing
over it: **browsers do not allow JavaScript to send raw UDP packets**,
which means this PWA cannot send an actual Wake-on-LAN magic packet.
This only works if the laptop is already powered on (asleep is fine if
your Windows power plan allows network activity during sleep — see
below; fully off or hibernated is not reachable by this app at all).
If you want true wake-from-fully-off, that needs either a WoL-capable
router (many have this as a built-in feature, reachable from its own
app) or a native app with raw socket access — genuinely outside what a
web app can do, not a shortcut I skipped.

### Setup

**1. Laptop — set the password and start the listener:**
```bash
setx ARGUS_LAUNCHER_PASSWORD "your-strong-password-here"
# close and reopen the terminal so the new env var is visible, then:
python -c "import feature_toggles; feature_toggles.set_enabled('remote_launcher', True)"
python launcher_listener.py
```

**2. Laptop — find its local IP** (Command Prompt): `ipconfig` → look for
"IPv4 Address" under your active adapter (usually `192.168.x.x`).

**3. Laptop — keep the listener running automatically:** Task Scheduler
→ Create Task → Trigger: "At log on" → Action: `python.exe` with
arguments `launcher_listener.py` and "Start in" set to this project's
folder. Under Settings, enable "Run task as soon as possible after a
scheduled start is missed."

**4. Windows power settings**, if you want this reachable while the
laptop is asleep, not just fully awake: Control Panel → Power Options
→ Change plan settings → Change advanced power settings →
Sleep → "Allow wake timers" → On, and in Device Manager, your network
adapter's Properties → Power Management → "Allow this device to wake
the computer."

**5. Phone — install the app:** open `http://<laptop-ip>:8765` in your
phone's browser, then use "Add to Home Screen" (Safari) or the install
prompt (Chrome). It opens full-screen, no browser chrome, like a real
app. First launch walks through setup (laptop address, your PIN, the
password from step 1). After that: open it, enter your PIN, done.

## 15. Protocol No Slop — strips AI filler, not Argus's actual voice

Every `casual_chat` response now passes through a filter before it
reaches you, catching the generic writing patterns small local models
lean on especially hard: throat-clearing openers ("Here's the thing"),
faux-insight setups ("What nobody tells you"), binary-contrast clichés
("It's not X. It's Y."), colon-reveal setups, fake-profound endings,
and filler closers ("I hope this helps!").

**Where this came from:** inspired by petergyang/no-ai-slop, a real
July 2026 open-source pattern list. That project ships as a Claude-Code
skill (a prompt file), not a portable library — there was nothing to
import — so `slop_filter.py` is an independent implementation of the
same category of detection, built as an actual Python module because
that's what fits here.

**Why this is scoped the way it is:** two tiers, on purpose. Filler
openers/closers and formatting bloat are stripped mechanically (regex,
instant, zero extra cost) because deleting them leaves a complete
sentence behind. Structural patterns (binary contrasts, colon reveals)
are only *detected* by regex, then fixed with one targeted
`FAST_MODEL` call — and only when something was actually found, so a
clean response never pays for it. Deleting those mechanically would
just leave a broken sentence.

**The adversarial case that actually mattered while building this:**
Argus's own personality — the Tanglish, the sarcasm, "macha"/"da"/"seri"
— is not slop, and a filter that flattened it would be a straightforward
regression, not an improvement. That's a real test in `slop_filter.py`'s
own `_self_test()`, not an assumption: a full response in Argus's actual
voice goes in, and comes out completely untouched. Also tested: normal
colon usage (a list intro), normal moderate bold, and a genuine
non-cliché "not X, it's Y" correction — none of those trigger anything.

On by default (`no_slop`, category Core) — it's a pure quality pass
with no new attack surface, same reasoning as Semantic Context
Compaction defaulting on. Turn it off in the control center if you'd
rather see the raw model output.

## 16. Protocol Frontier Escalation — the honest version of "know everything"

There's no version of "no training, knows everything" that's real, on
any hardware, built by anyone — that's not how any language model
works, including the biggest ones. What's actually achievable: an
explicit, opt-in handoff to a real frontier model for the rare
question that's genuinely beyond what `llama3.1:8b` reasons well
about. Not a bigger local brain — a local brain that can phone a
bigger one, on purpose, when you say so.

**This is the only protocol in Argus where a query leaves the local
network as part of normal reasoning.** Not MCP Bridge (a local stdio
tool server you configured), not graph_sync (LAN-only). This one calls
Anthropic's API over the internet. That's a real, deliberate exception
to everything else this project does, and it's treated like one:

- **Off by default.**
- **Never fires without confirmation** — say the trigger phrase, get
  told exactly what's about to be sent and to where, then have to say
  "confirmed" to actually send it. This holds even if brain.py's small
  routing model misclassifies an ordinary question into this action —
  it's a 1B model, it will occasionally be wrong — because the gate is
  structural (`confirmed=False` always short-circuits before any
  network call), not just careful prompt wording.
- **Deliberately narrow trigger language** — "ask a bigger model,"
  "escalate this to the cloud," not just any hard question. Try asking
  something genuinely difficult *without* that phrasing: it should
  route to `casual_chat` or `autonomous_workflow`, not here.
- **Has a real, ongoing cost** — unlike everything else in this
  project, which runs on hardware you already own. `recent_escalations()`
  in `frontier_escalation.py` exists so "is this quietly costing me
  money" has a real, checkable answer.

### Setup

```bash
pip install anthropic
export ANTHROPIC_API_KEY="your-key-here"      # same env var the official SDK already looks for
python -c "import feature_toggles; feature_toggles.set_enabled('frontier_escalation', True)"
```

Then: *"ask a bigger model to help me think through this database schema"*.

### Honest limitation

The `anthropic` package isn't installed in the environment this was
built in, and there's no network there to install it or a real API key
to call with — so unlike most of this project, the actual API call
could not be run end-to-end before delivery. What WAS tested: the
confirmation gate (never sends without `confirmed=True`), the toggle
check, and clean error handling for a missing key or missing package
— see `frontier_escalation.py`'s own `_self_test()`. Worth knowing: one
of the tests along the way had a bug in the test itself, not the code
— a mock that recursively called its own patched version instead of
the real one — caught and fixed before this shipped, not after.

## 17. Reaching Argus from anywhere, not just your home WiFi

Everything built so far — the control center, macro deck, screen mirror
and cursor control, the Wireless Launcher — is reachable from your
phone only when it's on the *same network* as the laptop. A local IP
like `192.168.1.42` or `10.16.172.173` isn't routable over the public
internet at all; that's not a configuration problem, it's what "local"
means. If you want your phone to reach the laptop from a coffee shop
or on cellular data, that's a genuinely different problem, and worth
solving the right way rather than the fast, risky way.

### What I'm not recommending, and why

**Port forwarding your router to the laptop** is the traditional answer
to this, and I'd steer you away from it here specifically. It exposes
whatever's on that port to the entire internet, not just you — and
`gatekeeper_mfa` (the login check for the dashboard) defaults to *off*
in this project. Forwarding a port without that on first means anyone
who finds the address, by scan or by luck, has no login to get past.
Most home ISPs also use CGNAT these days, so you may not even have a
public IP to forward to.

### What I'm recommending: a mesh VPN (Tailscale)

[Tailscale](https://tailscale.com) (or the similar ZeroTier) creates a
private network between just your own devices — laptop and phone —
using WireGuard underneath. No router configuration, no exposed public
port, no port-forwarding at all. Once both devices are on your
"tailnet," the laptop gets a stable private IP (something like
`100.x.x.x`) that your phone can reach from anywhere, exactly as if
they were on the same WiFi. Free for personal use.

**Setup:**
1. Install Tailscale on the laptop, sign in, note the IP it gives you
   (`tailscale ip -4`, or check the Tailscale tray icon).
2. Install the Tailscale app on your phone, sign into the *same*
   account.
3. Use that Tailscale IP anywhere you'd have used the local WiFi IP —
   the Wireless Launcher PWA's setup screen, the control center URL in
   your phone's browser, all of it. Nothing about Argus's own code
   needs to change; this is solved entirely at the network layer.

**Turn on `gatekeeper_mfa` before you rely on this**, even though
Tailscale already limits who can reach the laptop to devices on your
own tailnet. Defense in depth: if your phone is ever lost or someone
else's device somehow joins your tailnet, the dashboard should still
ask for something more than "did the request arrive from an allowed
IP."

### The one thing that doesn't work the same over Tailscale

`graph_sync`'s peer discovery uses a UDP **broadcast** — that's a
LAN-only mechanism, and it doesn't cross a mesh VPN like Tailscale
(those are point-to-point tunnels, not a shared broadcast domain, so
there's nothing for a broadcast packet to reach). This was a real gap
until now: `graph_sync_now`'s target can be a direct IP instead of the
literal word `"sync"` — give it a peer's Tailscale IP directly
(`"100.101.102.103"`) and it connects straight there, skipping
discovery entirely, exactly like Wireless Launcher already does. Same
underlying `pull_graph_from_peer()` either way; only the "how do I find
the peer" step changes.
