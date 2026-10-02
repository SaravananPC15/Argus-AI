import os
import time
import json
import py_compile
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import ollama

class CodeWatcher(FileSystemEventHandler):
    def __init__(self):
        self.last_trigger = 0

    def on_modified(self, event):
        # We only care about Python files, and ignore directories
        if event.is_directory or not event.src_path.endswith('.py'):
            return

        # Debounce: Prevent double-triggers because IDEs often save files twice rapidly
        current_time = time.time()
        if current_time - self.last_trigger < 5:
            return
        self.last_trigger = current_time

        filepath = event.src_path
        filename = os.path.basename(filepath)
        
        # Don't let Argus monitor his own core files, or we create an infinite loop!
        if filename in ["sentinel.py", "wake_agent.py", "tactical_hud.py", "brain.py"]:
            return

        print(f"[Sentinel] Tripwire triggered on {filename}. Running silent check...")
        
        try:
            # ZERO-RAM SYNTAX CHECK: Instantly catches typos without using Llama
            py_compile.compile(filepath, doraise=True)
            print(f"[Sentinel] {filename} is clean. Matrix stable.")
            
        except py_compile.PyCompileError as e:
            print(f"[Sentinel] Syntax Crash detected in {filename}! Waking the Llama Core...")
            
            # Extract the raw error string
            error_msg = str(e).strip()[-400:] 
            
            # Force the Llama core to explain the bug in Tanglish
            prompt = f"""
            You are Argus. The user just saved '{filename}' but there is a syntax bug: {error_msg}. 
            Explain exactly what they missed (like a missing colon, wrong indent, or unclosed parenthesis).
            Keep it to 2 casual Tanglish sentences. Use words like 'macha' or 'bro'. Do not use code blocks.
            """
            
            try:
                response = ollama.chat(model='llama3.2:1b', messages=[{'role': 'system', 'content': prompt}])
                warning_speech = response['message']['content'].strip()
                
                # DEAD-DROP THE PAYLOAD: We reuse the security alert file from your wake_agent!
                alert_payload = {"alert": warning_speech}
                with open("audio_cache/security_alert.json", "w") as f:
                    json.dump(alert_payload, f)
                    
                print(f"[Sentinel] Warning broadcasted to audio matrix: {warning_speech}")
            except Exception as llm_error:
                print(f"[Sentinel Llama Error]: {llm_error}")

def start_sentinel(path="."):
    """Boots up the Sentinel file system observer."""
    event_handler = CodeWatcher()
    observer = Observer()
    # Monitors the folder you run the script in
    observer.schedule(event_handler, path, recursive=False)
    observer.start()
    
    print("========================================")
    print("ARGUS SENTINEL MATRIX: ONLINE")
    print(f"Target Directory: {os.path.abspath(path)}")
    print("Listening for code modifications...")
    print("========================================")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Shutting down Sentinel Matrix...]")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    # Ensure audio cache exists for the dead-drop
    os.makedirs("audio_cache", exist_ok=True)
    start_sentinel()