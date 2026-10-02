import os
import shutil
import time
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# The staging area Argus will monitor
TRACKED_FOLDER = "./Argus_Inbox"

# The Routing Matrix: Dictates where files get banished to
ROUTING_MATRIX = {
    "textbooks": [".pdf", ".epub", ".docx", ".txt"],
    "video_assets": [".mp4", ".mov", ".mkv", ".avi"],
    "images": [".jpg", ".png", ".webp", ".jpeg"],
    "scripts": [".py", ".sh", ".html", ".css"]
}

class ForgeJanitor(FileSystemEventHandler):
    def on_created(self, event):
        # We only care about files, not new folders
        if event.is_directory:
            return
        
        filepath = event.src_path
        filename = os.path.basename(filepath)
        _, ext = os.path.splitext(filename)
        ext = ext.lower()

        # Slight delay to ensure the file is completely downloaded/saved before moving
        time.sleep(2)

        for category, extensions in ROUTING_MATRIX.items():
            if ext in extensions:
                # Route everything into the secure vault structure
                target_dir = f"./secure_vault/{category}"
                os.makedirs(target_dir, exist_ok=True)
                
                target_path = os.path.join(target_dir, filename)
                
                try:
                    shutil.move(filepath, target_path)
                    print(f"\n[Forge] Target acquired: {filename}")
                    print(f"[Forge] Banished to -> {target_dir}")
                    
                    # Tactical Tanglish Audio Notification ONLY for your YouTube video assets
                    if category == "video_assets":
                        alert_text = f"Macha, I just caught a new video file. I've routed {filename} directly to your secure video assets."
                        with open("audio_cache/security_alert.json", "w") as f:
                            json.dump({"alert": alert_text}, f)
                            
                except Exception as e:
                    print(f"[Forge Error] File locked or unmovable: {e}")
                break

def start_forge():
    # Ensure our staging and cache folders exist
    os.makedirs(TRACKED_FOLDER, exist_ok=True)
    os.makedirs("audio_cache", exist_ok=True)
    
    print("========================================")
    print("ARGUS FORGE MATRIX: ONLINE")
    print(f"Autonomous Janitor is watching: {os.path.abspath(TRACKED_FOLDER)}")
    print("Drop a file in the Inbox and watch it disappear.")
    print("========================================")
    
    event_handler = ForgeJanitor()
    observer = Observer()
    observer.schedule(event_handler, TRACKED_FOLDER, recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1) # Zero RAM infinite loop
    except KeyboardInterrupt:
        print("\n[Shutting down Forge Matrix...]")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    start_forge()