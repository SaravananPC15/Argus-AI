import subprocess
import psutil
import os
import sys
import re
import asyncio
import platform
from PIL import ImageGrab
import ollama
import pyautogui
import json
import pyperclip
import time
import model_router
import audit

if os.name == 'nt':
    import ctypes
else:
    ctypes = None  # Feature 11: ctypes.windll is Windows-only; guarded below


def _feature_on(toggle_key: str) -> bool:
    """Shared helper: checks feature_toggles.py without letting an import
    hiccup ever block an action from running (fail-open on error)."""
    try:
        import feature_toggles
        return feature_toggles.is_enabled(toggle_key)
    except Exception:
        return True


def run_local_command(action, target):
    """Public entry point. Wraps _run_local_command_impl so every call
    gets audit-logged in one place (Feature 12), regardless of which of
    the many early-return branches below actually produced the result."""
    result = _run_local_command_impl(action, target)
    audit.log_action(action, target, result)
    return result


def _run_local_command_impl(action, target):
    """Executes physical OS commands, system workflows, vision tasks, and developer operations."""
    try:
        # 1. APPLICATION LAUNCH MATRIX
        if action == "open_app":
            if os.name == 'nt':
                app_map = {
                    "notepad": "notepad.exe",
                    "calculator": "calc.exe",
                    "browser": "start msedge",
                    "command prompt": "cmd.exe"
                }
            elif sys.platform == 'darwin':
                app_map = {
                    "notepad": "open -a TextEdit",
                    "calculator": "open -a Calculator",
                    "browser": "open -a Safari",
                    "command prompt": "open -a Terminal"
                }
            else:
                app_map = {
                    "notepad": "gedit",
                    "calculator": "gnome-calculator",
                    "browser": "xdg-open http://",
                    "command prompt": "x-terminal-emulator"
                }
            app_name = target.lower().strip()
            cmd = app_map.get(app_name, app_name)
            subprocess.Popen(cmd, shell=True)
            return f"I have executed the launch sequence for {target}."
            
        # 2. SYSTEM & HARDWARE CONTROL MATRIX
        elif action == "system_command":
            target_lower = target.lower()
            
            if "ram" in target_lower or "cpu" in target_lower or "resource" in target_lower:
                cpu = psutil.cpu_percent(interval=0.5)
                ram = psutil.virtual_memory().percent
                return f"System telemetry confirms CPU usage is at {cpu} percent, and RAM is at {ram} percent."
            elif "pause" in target_lower or "play" in target_lower:
                pyautogui.press('playpause')
                return "Media playback has been toggled."
            elif "mute" in target_lower:
                pyautogui.press('volumemute')
                return "System audio has been muted."
            elif "volume up" in target_lower:
                pyautogui.press('volumeup', presses=10)
                return "I have increased the system volume."
            elif "volume down" in target_lower:
                pyautogui.press('volumedown', presses=10)
                return "I have decreased the system volume."
            elif "lock" in target_lower or "secure" in target_lower:
                # Feature 11: workstation locking is Windows-only via ctypes;
                # provide the macOS/Linux equivalents where possible.
                if ctypes is not None:
                    ctypes.windll.user32.LockWorkStation()
                    return "The workstation has been securely locked."
                elif sys.platform == 'darwin':
                    os.system("pmset displaysleepnow")
                    return "The display has been put to sleep (macOS has no direct 'lock' syscall from here, so this is the closest equivalent)."
                else:
                    lock_result = os.system("loginctl lock-session 2>/dev/null || xdg-screensaver lock 2>/dev/null")
                    if lock_result == 0:
                        return "The workstation has been securely locked."
                    return "I couldn't find a supported lock command on this Linux distro."
            elif "network" in target_lower or "internet" in target_lower:
                # Feature 11: Windows' ping uses -n, macOS/Linux use -c
                ping_flag = "-n" if os.name == 'nt' else "-c"
                devnull = "nul" if os.name == 'nt' else "/dev/null"
                response = os.system(f"ping {ping_flag} 1 8.8.8.8 > {devnull} 2>&1")
                if response == 0:
                    return "Network connection is stable and active."
                else:
                    return "We are currently offline. No external network access detected."
            elif "status" in target_lower or "report" in target_lower:
                ports = len(psutil.net_connections(kind='inet'))
                return f"The security matrix is online and active. I am currently tracking {ports} net connections. All local vault structures remain intact."

            return "I received the system command, but the specific execution path isn't mapped yet."
                
        # 3. ON-DEMAND SCREEN ANALYSIS (MOONDREAM)
        elif action == "vision_task":
            screenshot_path = "audio_cache/screenshot.png"
            screenshot = ImageGrab.grab()
            screenshot.save(screenshot_path)
            print("[Vision Matrix] Analyzing current screen frame...")
            response = ollama.chat(
                model=model_router.select_model("vision_task"),
                messages=[{'role': 'user', 'content': 'Briefly describe what is visible on this computer screen in 1 or 2 short sentences. Talk like a casual human.', 'images': [screenshot_path]}]
            )
            return f"I'm looking at your screen right now. {response['message']['content'].strip()}"

        # 4. CONTINUOUS ROOM AWARENESS (YOLOv8)
        elif action == "room_awareness":
            vision_file = "audio_cache/current_vision.json"
            if not os.path.exists(vision_file):
                return "My optical sensor is currently offline. I cannot see the room."
            with open(vision_file, 'r') as f:
                vision_data = json.load(f)
            if not vision_data:
                return "I am scanning the room, but I don't detect any identifiable objects right now."
            objects_seen = []
            for obj, count in vision_data.items():
                if count == 1:
                    objects_seen.append(f"one {obj}")
                else:
                    objects_seen.append(f"{count} {obj}s")
            return f"Through the camera feed, I currently see {', '.join(objects_seen)}."
            
        # 5. DEVELOPER TOOLS: READ CODE
        elif action == "read_file":
            filename = target.strip()
            if not os.path.exists(filename):
                return f"I am checking the directory, but I cannot find a file named {filename}."
            with open(filename, 'r', encoding='utf-8') as f:
                code_snippet = f.read()[:1000]
            print(f"[Developer Matrix] Analyzing {filename}...")
            analysis_prompt = f"Briefly explain what this code does in 2 conversational sentences so I can read it out loud to the user:\n\n{code_snippet}"
            analysis_response = ollama.chat(model=model_router.select_model("read_file"), messages=[{'role': 'system', 'content': analysis_prompt}])
            return analysis_response['message']['content'].strip()

        # 6. DEVELOPER TOOLS: EXECUTE & AUTO-DEBUG
        elif action == "run_script":
            script_name = target.strip()
            if not os.path.exists(script_name):
                return f"I cannot initiate the sequence because {script_name} does not exist in the active directory."
            print(f"[Developer Matrix] Executing {script_name}...")

            # Protocol Shadow Sandbox Execution: runs through sandbox.py
            # (Docker if available, else a restricted subprocess -- see
            # that module's docstring for exactly how much isolation each
            # path actually provides) instead of a bare subprocess call,
            # so a runaway script can't hang or OOM the whole assistant.
            # Falls back to the original bare-subprocess behavior if the
            # protocol is toggled off.
            if _feature_on("shadow_sandbox"):
                import sandbox
                with open(script_name) as f:
                    code = f.read()
                sandbox_result = sandbox.run_sandboxed(code, timeout=15)
                if sandbox_result["timed_out"]:
                    return (f"{script_name} was still running after 15 seconds, so I killed it "
                             f"(Protocol Shadow Sandbox Execution).")
                returncode = sandbox_result["returncode"]
                stdout, stderr = sandbox_result["stdout"], sandbox_result["stderr"]
            else:
                # Feature 11: use the same interpreter running Argus itself
                # rather than assuming a "python" command exists on PATH.
                result = subprocess.run([sys.executable, script_name], capture_output=True, text=True, timeout=15)
                returncode, stdout, stderr = result.returncode, result.stdout, result.stderr

            if returncode == 0:
                output = stdout.strip()
                if not output:
                    return f"I ran {script_name}. It executed successfully with no terminal output."
                return f"I successfully executed {script_name}. The terminal output is: {output[:100]}"
            else:
                error_trace = stderr.strip()[-600:]
                print(f"[Developer Matrix] Crash detected. Analyzing traceback...")
                bug_prompt = f"The user's python script crashed. Explain this error traceback in 2 short, conversational sentences, and suggest a fix. Do not use markdown.\n\n{error_trace}"
                bug_response = ollama.chat(model=model_router.select_model("run_script"), messages=[{'role': 'system', 'content': bug_prompt}])
                return f"The script crashed during execution. {bug_response['message']['content'].strip()}"

        # 7. AUTONOMOUS RESEARCHER (DEEP DIVE MATRIX)
        elif action == "deep_research":
            topic = target.strip()
            print(f"[Developer Matrix] Routing to Deep Dive Protocol for: {topic}")
            from research_agent import run_deep_dive
            return run_deep_dive(topic)

        # 8. PROTOCOL SIGMA: PHANTOM CLIPBOARD
        elif action == "read_clipboard":
            print("[Phantom Clipboard] Sniffing system memory...")
            clipboard_data = pyperclip.paste()
            
            if not clipboard_data or len(clipboard_data.strip()) == 0:
                return "The clipboard is empty, macha. Copy some text first."

            # Truncate to 2000 chars to protect RAM during analysis
            safe_text = clipboard_data[:2000]
            print("[Phantom Clipboard] Data acquired. Analyzing...")
            
            analysis_prompt = f"The user copied this text to their clipboard. Summarize or explain it briefly in 2-3 casual Tanglish sentences:\n\n{safe_text}"
            analysis_response = ollama.chat(model=model_router.select_model("read_clipboard"), messages=[{'role': 'system', 'content': analysis_prompt}])
            
            return analysis_response['message']['content'].strip()

        # 9. PROTOCOL ECHO: GHOST TYPER
        elif action == "ghost_type":
            print(f"[Ghost Typer] Drafting text for: {target}")
            
            # Force the brain to draft the raw text first
            draft_prompt = f"Write a short, clean block of text or code for: '{target}'. Do not use markdown formatting blocks like ```python, just output the raw text so it can be typed directly onto the screen."
            draft_response = ollama.chat(model=model_router.select_model("ghost_type"), messages=[{'role': 'system', 'content': draft_prompt}])
            content_to_type = draft_response['message']['content'].strip()

            # Give a 4-second delay to click into the target window
            print("\n[Ghost Typer] ENGAGING KEYBOARD IN 4 SECONDS. CLICK YOUR TARGET WINDOW NOW!\n")
            time.sleep(4)
            
            # Physically type it out
            pyautogui.write(content_to_type, interval=0.03) 
            
            return "I have executed the ghost typing sequence, macha. The draft is on your screen."

        # 10. PROTOCOL OMNI: APP BRIDGE
        elif action == "connect_app":
            from app_bridge import handle_app_connection
            print(f"[Omni Bridge] Initializing connection protocols...")
            return handle_app_connection(target)

        # 11. PROTOCOL CHRONOS: THE TIME MATRIX
        elif action == "schedule_task":
            import schedule
            print(f"[Chronos Matrix] Parsing scheduling parameters...")
            parse_prompt = f"The user wants to schedule a task. Extract the 24-hour time (HH:MM) and the specific command to run. Output ONLY valid JSON with keys 'time' and 'command'. Text: '{target}'"
            
            try:
                parse_response = ollama.chat(model=model_router.select_model("schedule_task"), messages=[{'role': 'system', 'content': parse_prompt}], format='json')
                parsed_data = json.loads(parse_response['message']['content'].strip())
                
                run_time = parsed_data.get("time")
                run_cmd = parsed_data.get("command")
                
                if not run_time or not run_cmd:
                    return "Macha, I couldn't extract the exact time or command. Give me a clear time like '06:00'."

                # The payload writer that drops a dead-drop file for the wake_agent to catch
                def trigger_chronos(cmd_text):
                    print(f"\n[Chronos] Scheduled time reached! Dropping payload for: {cmd_text}")
                    with open("audio_cache/chronos_trigger.txt", "w") as f:
                        f.write(cmd_text)
                        
                schedule.every().day.at(run_time).do(trigger_chronos, cmd_text=run_cmd)
                return f"Protocol Chronos engaged, macha. I will execute '{run_cmd}' every day at {run_time}."
                
            except Exception as e:
                print(f"[Chronos Error]: {e}")
                return "I ran into a glitch trying to parse that schedule, bro."

        # 12. PROTOCOL SHADOW: GIT MASTER
        elif action == "git_push":
            import git
            print(f"[Shadow Matrix] Initiating Git sequence for directory: {os.getcwd()}")
            
            try:
                # Target the current working directory
                repo = git.Repo(".", search_parent_directories=True)
                
                if not repo.is_dirty(untracked_files=True):
                    return "Macha, the repository is already clean. Nothing to commit."
                
                # Stage all changes
                repo.git.add(A=True)
                diff = repo.git.diff(staged=True)
                
                if not diff:
                    return "I staged the files, but the diff is empty. Matrix stable."

                guardian_note = ""
                try:
                    import feature_toggles
                    if feature_toggles.is_enabled("syntax_guardian"):
                        import syntax_guardian
                        dirty_files = [item.a_path for item in repo.index.diff(None)] + \
                                      [item.a_path for item in repo.index.diff("HEAD")] + repo.untracked_files
                        dirty_py_files = [f for f in set(dirty_files) if f.endswith(".py") and os.path.exists(f)]
                        if dirty_py_files:
                            print(f"[Syntax Guardian] Screening {len(dirty_py_files)} Python files before commit...")
                            guard_result = syntax_guardian.guard_files(dirty_py_files)
                            guardian_note = syntax_guardian.summarize_for_speech(guard_result)
                            # Re-stage in case autopep8 modified any files
                            repo.git.add(A=True)
                            diff = repo.git.diff(staged=True)
                except Exception as e:
                    print(f"[Syntax Guardian] Skipped due to error: {e}")

                # Truncate diff to save your 8GB RAM Llama context window
                safe_diff = diff[:1500] 
                
                print("[Shadow Matrix] Analyzing code changes for commit message...")
                prompt = f"Write a professional, concise 1-sentence Git commit message for these code changes. Do not use quotes or markdown. Diff: {safe_diff}"
                
                response = ollama.chat(model=model_router.select_model("git_push"), messages=[{'role': 'system', 'content': prompt}])
                commit_msg = response['message']['content'].strip()
                
                # Commit and Push
                repo.index.commit(commit_msg)
                current_branch = repo.active_branch.name
                origin = repo.remote(name='origin')
                
                print("[Shadow Matrix] Pushing to remote...")
                origin.push(current_branch)

                # Feature: keep the git archeologist / mind map graph fresh
                try:
                    import nexus_graph
                    nexus_graph.add_node(f"commit:{repo.head.commit.hexsha[:10]}", commit_msg[:60], "commit", {"branch": current_branch})
                except Exception:
                    pass
                
                return f"{guardian_note}Protocol Shadow complete, bro. I committed with the message: '{commit_msg}' and pushed to {current_branch}."
                
            except git.exc.InvalidGitRepositoryError:
                return "Bro, the current directory isn't a valid Git repository. Initialize it first."
            except Exception as e:
                print(f"[Shadow Error]: {e}")
                return "I hit a snag trying to push the code. Check your remote connection or SSH keys."

        # 13. FEATURE 8: CALENDAR
        elif action == "calendar":
            from calendar_agent import handle_calendar_request
            print("[Calendar Matrix] Parsing calendar request...")
            return handle_calendar_request(target)

        # 14. FEATURE 8: EMAIL
        elif action == "send_email":
            from email_agent import handle_email_request
            print("[Email Matrix] Parsing email request...")
            return handle_email_request(target)

        # 15. PROTOCOL CASTELLAN: ENROLL DEVICE
        elif action == "castellan_enroll":
            if not _feature_on("castellan"):
                return "Protocol Castellan is currently toggled off in the control center."
            import castellan
            print("[Castellan] Scanning for nearby Bluetooth devices...")
            try:
                devices = asyncio.run(castellan.scan_for_devices(timeout=6.0))
            except Exception as e:
                print(f"[Castellan Error]: {e}")
                return "Bluetooth scan failed — make sure Bluetooth is on and 'bleak' is installed."
            if not devices:
                return "No nearby Bluetooth devices found, macha. Make sure your phone's Bluetooth is on and discoverable."
            top = devices[0]
            castellan.enroll_device(top["address"], top["name"])
            return f"Enrolled {top['name']} ({top['address']}) as your proximity key — strongest signal in range."

        # 16. PROTOCOL GIT ARCHEOLOGIST
        elif action == "git_archeology":
            if not _feature_on("git_archeologist"):
                return "Protocol Git Archeologist is currently toggled off in the control center."
            import git_archeologist
            filepath, _, function_name = target.partition("|")
            print(f"[Git Archeologist] Digging through history for {filepath.strip()}...")
            return git_archeologist.generate_report(filepath.strip(), function_name.strip() or None)

        # 17. PROTOCOL DATASET SYNTH
        elif action == "dataset_synth":
            if not _feature_on("dataset_synth"):
                return "Protocol Dataset Synth is currently toggled off in the control center."
            import dataset_synth
            print("[Dataset Synth] Parsing schema and generating rows...")
            return dataset_synth.generate_dataset(target)

        # 18. PROTOCOL MULTI-AGENT COUNCIL
        elif action == "multi_agent_council":
            if not _feature_on("multi_agent_council"):
                return "Protocol Multi-Agent Council is currently toggled off in the control center."
            import council
            print(f"[Council] Convening on: {target}")
            return council.handle_council_request(target)

        # 19. PROTOCOL SYNTAX GUARDIAN (standalone check, not tied to a push)
        elif action == "syntax_guardian_check":
            if not _feature_on("syntax_guardian"):
                return "Protocol Syntax Guardian is currently toggled off in the control center."
            import syntax_guardian
            filepath = target.strip()
            if not os.path.exists(filepath):
                return f"I can't find {filepath} to lint."
            result = syntax_guardian.guard_files([filepath])
            return syntax_guardian.summarize_for_speech(result) or f"{filepath} is already clean."

        # 20. PROTOCOL SMART LOG DIGEST
        elif action == "log_digest":
            if not _feature_on("smart_log_digest"):
                return "Protocol Smart Log Digest is currently toggled off in the control center."
            import log_digest
            print("[Log Digest] Aggregating today's activity...")
            return log_digest.generate_digest()

        # 21. PROTOCOL MIND MAP EXPORTER
        elif action == "mind_map_export":
            if not _feature_on("mind_map_exporter"):
                return "Protocol Mind Map Exporter is currently toggled off in the control center."
            import mind_map_exporter
            print("[Mind Map] Rendering nexus graph...")
            return mind_map_exporter.export_mind_map()

        # 22. PROTOCOL SCRAPING VANGUARD
        elif action == "scraping_vanguard":
            if not _feature_on("scraping_vanguard"):
                return "Protocol Scraping Vanguard is currently toggled off in the control center."
            import scraping_vanguard
            print("[Scraping Vanguard] Gathering public data...")
            return scraping_vanguard.gather_from_sources(target)

        # 23. PROTOCOL SYNTHETIC ANCHOR
        elif action == "synthetic_anchor":
            if not _feature_on("synthetic_anchor"):
                return "Protocol Synthetic Anchor is currently toggled off in the control center."
            import synthetic_anchor
            print(f"[Synthetic Anchor] Searching local project data for: {target}")
            return synthetic_anchor.handle_search_request(target)

        # 24. PROTOCOL AUTO-DOCUMENTATION
        elif action == "auto_documentation":
            if not _feature_on("auto_documentation"):
                return "Protocol Auto-Documentation is currently toggled off in the control center."
            import auto_documentation
            print(f"[Auto-Documentation] Drafting docstrings for {target}...")
            return auto_documentation.document_file(target.strip())

        # 25. SELF-DEVELOPMENT ENGINE STATUS
        elif action == "self_dev_status":
            import self_dev
            if not _feature_on("self_dev_engine"):
                pending = len(self_dev.get_pending_patches())
                return (f"Self-Development Engine is toggled off right now, macha. "
                        f"There are {pending} old proposals still sitting in the log if you want to review them.")
            print("[Self-Dev] Running a diagnosis + feature-gap pass...")
            self_dev.run_cycle()
            pending = self_dev.get_pending_patches()
            if not pending:
                return "Self-diagnosis came back clean — no broken imports or syntax errors, and no repeated feature gaps right now."
            return f"Found {len(pending)} thing(s) worth reviewing. Check the Log History panel to approve or reject them — I never apply these myself."

        # 26. PROTOCOL ROUND TABLE
        elif action == "round_table":
            if not _feature_on("round_table"):
                return "Protocol Round Table is currently toggled off in the control center."
            import round_table
            print(f"[Round Table] Convening specialists on: {target}")
            return round_table.handle_round_table_request(target)

        # 27. PROTOCOL VIRTUAL TERMINAL EXTENSION (run a saved macro)
        elif action == "run_macro":
            if not _feature_on("virtual_terminal"):
                return "Protocol Virtual Terminal Extension is currently toggled off in the control center."
            import macro_deck
            print(f"[Macro Deck] Running macro: {target}")
            return macro_deck.run_macro(target.strip())

        # 28. PROTOCOL DYNAMIC SEQUENCE SHARDING
        elif action == "shard_analyze":
            if not _feature_on("sequence_sharding"):
                return "Protocol Dynamic Sequence Sharding is currently toggled off in the control center."
            import sequence_sharding
            filename, _, question = target.partition("|")
            filename = filename.strip()
            question = question.strip() or "Summarize the key points."
            if not os.path.exists(filename):
                return f"I can't shard {filename} because it doesn't exist in the active directory."
            with open(filename, errors="ignore") as f:
                content = f.read()
            print(f"[Sequence Sharding] Analyzing {filename} ({len(content)} chars) in shards...")
            return sequence_sharding.analyze_large_input(content, question)

        # 29. PROTOCOL BIG-O COMPLEXITY AUDITOR
        elif action == "complexity_audit":
            if not _feature_on("complexity_auditor"):
                return "Protocol Big-O Complexity Auditor is currently toggled off in the control center."
            import complexity_auditor
            filename = target.strip()
            if not os.path.exists(filename):
                return f"I can't audit {filename} because it doesn't exist in the active directory."
            with open(filename, errors="ignore") as f:
                source = f.read()
            print(f"[Complexity Auditor] Analyzing {filename}...")
            try:
                reports = complexity_auditor.audit_source(source, filename=filename)
            except SyntaxError as e:
                return f"I couldn't parse {filename} as Python to audit it: {e}"
            return complexity_auditor.format_report(reports)

        # 30. PROTOCOL DATABASE INDEXING OPTIMIZER
        elif action == "db_index_optimize":
            if not _feature_on("db_index_optimizer"):
                return "Protocol Database Indexing Optimizer is currently toggled off in the control center."
            import db_index_optimizer
            db_path = target.strip()
            if not db_path or db_path.lower() == "optimize":
                db_path = db_index_optimizer.DEFAULT_DB_PATH
            print(f"[DB Index Optimizer] Analyzing {db_path}...")
            result = db_index_optimizer.optimize_database(db_path, apply=False)
            return db_index_optimizer.format_report(result)

        # 31. PROTOCOL RELATIONAL-TO-NOSQL TRANSPILER
        elif action == "sql_to_nosql":
            if not _feature_on("sql_to_nosql"):
                return "Protocol Relational-to-NoSQL Transpiler is currently toggled off in the control center."
            import sql_to_nosql
            raw_sql = target
            if os.path.exists(target.strip()):
                with open(target.strip(), errors="ignore") as f:
                    raw_sql = f.read()
            print("[SQL-to-NoSQL] Parsing schema...")
            tables = sql_to_nosql.parse_create_tables(raw_sql)
            if not tables:
                return "I couldn't find any CREATE TABLE statements in that — paste the schema or point me at a .sql file."
            schema = sql_to_nosql.to_document_schema(tables)
            return sql_to_nosql.format_report(schema)

        # 32. PROTOCOL ZERO-G VISUAL CONTROLS (status only -- the actual
        # gesture loop is a blocking camera loop meant to run as its own
        # background service via launch.py, not inline in a chat reply)
        elif action == "gesture_control_status":
            enabled = _feature_on("zero_g_visual")
            if enabled:
                return ("Protocol Zero-G Visual Controls is ON. If the background service isn't "
                        "running yet, start it from launch.py — see SETUP.md for the one-time "
                        "gesture model download it needs first.")
            return ("Protocol Zero-G Visual Controls is currently OFF. Flip it on in the control "
                    "center, then start the gesture_control service from launch.py.")

        # 33. PROTOCOL PEER-TO-PEER GRAPH SYNC
        elif action == "graph_sync_now":
            if not _feature_on("graph_sync"):
                return "Protocol Peer-to-Peer Graph Sync is currently toggled off in the control center."
            import graph_sync
            import nexus_graph
            import re as _re
            passphrase = os.environ.get("ARGUS_GRAPH_SYNC_PASSPHRASE")
            if not passphrase:
                return ("Graph Sync needs a shared passphrase set first — see SETUP.md for how to "
                        "set ARGUS_GRAPH_SYNC_PASSPHRASE on every device you want syncing.")

            # target is either "sync" (broadcast-discover peers on the local
            # network -- the original behavior) or a specific IP, direct.
            # Broadcast discovery doesn't cross a mesh VPN like Tailscale --
            # those are point-to-point tunnels, not a shared broadcast
            # domain -- but a direct IP connects over Tailscale exactly like
            # it would over LAN, since Tailscale just presents as another
            # routable network interface. Same reasoning as why the launcher
            # PWA's "laptop address" field already accepts a Tailscale IP.
            direct_ip_match = _re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target.strip())
            if direct_ip_match:
                peers = [target.strip()]
                print(f"[Graph Sync] Connecting directly to {peers[0]} (skipping broadcast discovery)...")
            else:
                print("[Graph Sync] Discovering peers on the local network...")
                peers = graph_sync.discover_peers(timeout=4.0)
            if not peers:
                return ("No peers responded on the local network. If you're syncing over Tailscale "
                        "or another network broadcast can't reach, give it the peer's IP directly "
                        "instead of just \"sync\" (see graph_sync.py's docstring if that's surprising).")
            current = nexus_graph.get_graph()
            merged = dict(current)
            synced_with = []
            for peer_ip in peers:
                try:
                    chunks = graph_sync.pull_graph_from_peer(peer_ip, passphrase)
                    merged = graph_sync.merge_graph(merged, chunks)
                    synced_with.append(peer_ip)
                except Exception as e:
                    print(f"[Graph Sync] Failed syncing with {peer_ip}: {e}")
            nexus_graph._save(merged)
            return f"Synced with {len(synced_with)}/{len(peers)} peer(s): {', '.join(synced_with) or 'none succeeded'}."

        # 34. PROTOCOL ACOUSTIC DATA LINK
        elif action == "send_acoustic_message":
            if not _feature_on("acoustic_link"):
                return "Protocol Acoustic Data Link is currently toggled off in the control center."
            import acoustic_link
            try:
                print(f"[Acoustic Link] Playing FSK tones for: {target}")
                acoustic_link.send_over_speaker(target.strip())
                return f"Sent \"{target.strip()}\" as audio tones — anything listening nearby should pick it up."
            except Exception as e:
                return f"Couldn't play the acoustic message ({e}) — check that a speaker/sounddevice is actually available on this machine."

        # 35. PROTOCOL MCP TOOL BRIDGE
        elif action == "mcp_list_tools":
            if not _feature_on("mcp_bridge"):
                return "Protocol MCP Tool Bridge is currently toggled off in the control center."
            import mcp_bridge
            servers = mcp_bridge.load_servers()
            if not servers:
                return ("No MCP servers configured yet. Add one with mcp_bridge.add_server(...) "
                        "— see SETUP.md — then ask me to list tools again.")
            print("[MCP Bridge] Refreshing tool list from configured servers...")
            tools_by_server = asyncio.run(mcp_bridge.refresh_tool_cache())
            lines = []
            for server_name, tools in tools_by_server.items():
                if not tools:
                    lines.append(f"{server_name}: unreachable or advertised no tools.")
                    continue
                for t in tools:
                    lines.append(f"{server_name}.{t['name']}: {t['description']}")
            return "\n".join(lines) if lines else "No tools found on any configured server."

        # 36. PROTOCOL MCP TOOL BRIDGE (invoke one tool)
        elif action == "mcp_call_tool":
            if not _feature_on("mcp_bridge"):
                return "Protocol MCP Tool Bridge is currently toggled off in the control center."
            import mcp_bridge
            # Expected target format: "server_name.tool_name: {"arg": "value"}"
            # A previously-blocked risky call is re-issued by including the
            # word "confirmed" anywhere in the target -- checked loosely
            # (not a strict prefix) since a small local routing model
            # reformatting a blocked call isn't perfectly consistent about
            # where it places things.
            confirmed = "confirmed" in target.lower()
            cleaned_target = re.sub(r"\bconfirmed\b", "", target, flags=re.IGNORECASE).strip()
            try:
                header, _, args_json = cleaned_target.partition(":")
                server_name, _, tool_name = header.strip().partition(".")
                arguments = json.loads(args_json.strip()) if args_json.strip() else {}
            except (ValueError, json.JSONDecodeError) as e:
                return (f"Couldn't parse that as 'server.tool: {{json args}}' ({e}). "
                        f"Try: mcp_list_tools first to see the exact names.")
            print(f"[MCP Bridge] Calling {server_name}.{tool_name} with {arguments} (confirmed={confirmed})...")
            try:
                result = asyncio.run(mcp_bridge.call_tool(server_name, tool_name, arguments, confirmed=confirmed))
            except ValueError as e:
                return str(e)
            if result.get("needs_confirmation"):
                return result["message"] + " Say it again with the word 'confirmed' to proceed."
            if not result.get("ok"):
                return f"MCP tool call failed: {result.get('error', 'unknown error')}"
            return "\n".join(result["result"])

        # 37. PROTOCOL FRONTIER ESCALATION
        elif action == "frontier_escalate":
            if not _feature_on("frontier_escalation"):
                return "Protocol Frontier Escalation is currently toggled off in the control center."
            import frontier_escalation
            # Same "confirmed" convention as mcp_call_tool just above -- checked
            # loosely (anywhere in the text), not a strict prefix, since a small
            # local routing model re-issuing a blocked request isn't perfectly
            # consistent about where it places things.
            confirmed = "confirmed" in target.lower()
            query = re.sub(r"\bconfirmed\b", "", target, flags=re.IGNORECASE).strip()
            print(f"[Frontier Escalation] Request (confirmed={confirmed}): {query[:60]}")
            result = frontier_escalation.escalate(query, confirmed=confirmed)
            if result.get("needs_confirmation"):
                return result["message"]
            if not result.get("ok"):
                return f"Couldn't reach the frontier model: {result.get('error', 'unknown error')}"
            return result["response"]

        return "I received the command, but the local execution path isn't fully mapped."
        
    except subprocess.TimeoutExpired:
        return f"I forcefully terminated {target} because it exceeded the execution safety timeout limit."
    except Exception as e:
        print(f"[Executor Error]: {e}")
        return "I hit a snag trying to execute that locally."
