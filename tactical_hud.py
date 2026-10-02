import tkinter as tk
import psutil
import json
import os
import time
import threading

class ArgusHUD:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ARGUS TACTICAL OVERLAY")
        
        # Make the window transparent, borderless, and click-through
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.config(bg="black")

        if os.name == 'nt':
            # Windows specific: true color-key transparency + click-through
            # (WS_EX_TRANSPARENT | WS_EX_LAYERED). Neither of these Win32
            # tricks has a direct equivalent on macOS/Linux Tk, so this
            # whole block is Feature 11-guarded.
            self.root.attributes("-transparentcolor", "black")
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            extended_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, extended_style | 0x00080000 | 0x00000020)
        else:
            # Best-effort equivalent: near-full alpha transparency instead
            # of true color-key transparency, and no click-through (the
            # window will intercept clicks on macOS/Linux).
            try:
                self.root.attributes("-alpha", 0.85)
            except tk.TclError:
                pass
            print("[Tactical HUD] Click-through overlay is Windows-only; "
                  "running with a semi-transparent, click-capturing window instead.")

        # HUD Text Element
        self.label = tk.Label(self.root, text="SYSTEM BOOT...", font=("Courier", 14, "bold"), 
                              fg="#00FF66", bg="black", justify="left", anchor="nw")
        self.label.pack(side="top", anchor="w", padx=20, pady=20)
        
        self.running = True
        self.update_thread = threading.Thread(target=self.gather_telemetry, daemon=True)
        self.update_thread.start()

    def gather_telemetry(self):
        while self.running:
            try:
                # 1. Hardware Combat Vitals
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                
                # 2. Optical Sensor (YOLO) Data Feed
                vision_text = "OPTICAL SENSOR: OFFLINE"
                vision_file = "audio_cache/current_vision.json"
                if os.path.exists(vision_file):
                    with open(vision_file, 'r') as f:
                        vision_data = json.load(f)
                    if vision_data:
                        targets = [f"{count}x {obj.upper()}" for obj, count in vision_data.items()]
                        vision_text = "TARGETS ACQUIRED:\n  > " + "\n  > ".join(targets)
                    else:
                        vision_text = "OPTICAL SENSOR: CLEAR"

                # 3. Security Warden Data
                alert_file = "audio_cache/security_alert.json"
                sec_status = "[ BREACH DETECTED ]" if os.path.exists(alert_file) else "[ SECURE ]"
                sec_color = "#FF0000" if os.path.exists(alert_file) else "#00FF66"

                hud_display = f"""
ARGUS // TACTICAL MATRIX
------------------------
CPU LOAD:  {cpu}%
MEM LOAD:  {ram}%
NETWORK:   {sec_status}

{vision_text}
------------------------
STANDING BY FOR COMMAND.
                """
                
                # Update UI safely
                self.label.config(text=hud_display, fg=sec_color)
                time.sleep(1)
            except Exception as e:
                pass

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    hud = ArgusHUD()
    hud.run()