import asyncio
import threading
import time
import os
import re
if os.name == 'nt':
    import winshell
else:
    winshell = None  # Feature 11: winshell is Windows-only; guarded below
from AppOpener import open as open_app
import pywhatkit
from voice import speak
from search_engine import search_web, ai_summarize_search
import safety

def parse_time_to_seconds(time_str):
    """Converts natural text strings like '5 minutes' or '10 seconds' into an integer count of seconds."""
    time_str = time_str.lower().strip()
    digits = re.findall(r'\d+', time_str)
    if not digits:
        return 0
    amount = int(digits[0])
    
    if "second" in time_str:
        return amount
    elif "minute" in time_str:
        return amount * 60
    elif "hour" in time_str:
        return amount * 3600
    return amount

def background_timer_worker(seconds, message):
    """Runs inside an isolated thread, counting down without blocking the main program."""
    time.sleep(seconds)
    print(f"\n\n[ALERT] Timer Finished: {message}")
    speak(f"Attention: {message}")

def confirm_risky_action(action, target):
    """Feature 4: speaks a confirmation prompt and listens for a spoken
    'confirm' before proceeding with a destructive/irreversible action."""
    from ears import listen_to_user  # local import avoids a circular import with ears.py
    speak(safety.confirmation_prompt(action, target))
    reply = listen_to_user()
    if reply and safety.is_confirmation(reply):
        return True
    speak("Okay, cancelled. No changes made.")
    return False

def execute_action(decision_json):
    if not decision_json:
        speak("I encountered an error trying to process that.")
        return

    action = decision_json.get("action")
    target = decision_json.get("target")

    print(f"[Debug] Action sent to Hands: '{action}' | Target: '{target}'")

    if action == "open_app":
        try:
            speak(f"Opening {target}")
            open_app(target, match_closest=True)
        except Exception:
            speak(f"I couldn't open {target}.")

    elif action in ["system_command", "empty_recycle_bin"]:
        if not confirm_risky_action("empty_recycle_bin", target):
            return
        if winshell is None:
            speak("The recycle bin feature only works on Windows, so I can't do that on this machine.")
            return
        try:
            speak("Emptying the recycle bin.")
            winshell.recycle_bin().empty(confirm=False, show_progress=False, sound=True)
        except Exception:
            speak("The recycle bin is already empty.")

    elif action == "casual_chat":
        speak(target)

    elif action == "memorize":
        from memory import save_memory
        save_memory(target)
        speak("Fact saved to my memory core.")
        
    elif action == "recall":
        from memory import ask_memory
        print(f"[Memory] Searching for: {target}")
        answer = ask_memory(target)
        speak(answer)

    elif action == "web_search":
        speak("Searching the web.")
        raw_results = search_web(target)
        clean_answer = ai_summarize_search(target, raw_results)
        speak(clean_answer)

    # --- THE FIXED ASYNCHRONOUS CLOCK MODULE ---
    elif action == "set_reminder":
        try:
            if "|" not in target:
                speak("The reminder format was parsed incorrectly by the cognitive matrix.")
                return
                
            time_part, message_part = target.split("|", 1)
            seconds = parse_time_to_seconds(time_part)
            reminder_msg = message_part.strip()
            
            if seconds > 0:
                speak(f"Setting a background timer for {time_part.strip()}.")
                # Spin up an independent background worker thread
                worker = threading.Thread(
                    target=background_timer_worker, 
                    args=(seconds, reminder_msg), 
                    daemon=True
                )
                worker.start()
            else:
                speak("I was unable to calculate the seconds from that duration string.")
        except Exception as e:
            print(f"[Clock Error] Thread spawning failed: {e}")
            speak("I encountered an error starting the background clock process.")

    # --- ACTION 6: THE SCRIBE (DOCUMENT READING) ---
    elif action == "read_document":
        from scribe import summarize_document
        speak(f"Accessing the document: {target}. Please wait while I read it.")
        
        # This might take 5-10 seconds depending on document length
        summary = summarize_document(target)
        speak(summary)

    # --- ACTION 7: PHYSICAL BROWSER CONTROL ---
    elif action == "browser_control":
        # browser_agent.py defines execute_browser_automation (async), not automate_browser
        from browser_agent import execute_browser_automation
        try:
            task, url = target.split("|", 1)
            speak(f"Piloting the browser to {url.strip()}")

            # execute_browser_automation is an async function, so it must be run via asyncio
            result = asyncio.run(execute_browser_automation(task.strip(), url.strip()))
            speak(result)
        except Exception as e:
            print(f"[Browser Control Error]: {e}")
            speak("I failed to parse the browser instructions.")

    # --- ACTIONS 8+: EVERYTHING ELSE BRAIN.PY CAN ROUTE TO ---
    # brain.py's routing matrix can also emit: vision_task, room_awareness,
    # run_script, read_file, deep_research, read_clipboard, ghost_type,
    # connect_app, schedule_task, and git_push. Those are implemented in
    # executor.py (the same module wake_agent.py / remote_server.py use),
    # so we delegate to it here instead of duplicating that logic.
    elif action in [
        "vision_task", "room_awareness", "run_script", "read_file",
        "deep_research", "read_clipboard", "ghost_type", "connect_app",
        "schedule_task", "git_push", "calendar", "send_email",
        "castellan_enroll", "git_archeology", "dataset_synth",
        "multi_agent_council", "syntax_guardian_check", "log_digest",
        "mind_map_export", "scraping_vanguard", "synthetic_anchor",
        "auto_documentation", "self_dev_status"
    ]:
        if safety.is_risky(action, target):
            if not confirm_risky_action(action, target):
                return
        from executor import run_local_command
        try:
            result = run_local_command(action, target)
            speak(result)
        except Exception as e:
            print(f"[Executor Delegation Error]: {e}")
            speak("I hit a snag trying to execute that locally.")

    else:
        speak(f"I am not programmed to do the action: {action}")