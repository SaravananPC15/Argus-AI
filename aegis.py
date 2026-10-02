import psutil
import time
import json
import os
import random
import notifier

# Cooldowns to prevent him from spamming you with audio warnings
CPU_COOLDOWN = 300      # 5 minutes between CPU warnings
BATTERY_COOLDOWN = 600  # 10 minutes between Battery warnings

def start_aegis():
    print("========================================")
    print("ARGUS AEGIS MATRIX: ONLINE")
    print("Hardware Guardian monitoring CPU and Power...")
    print("========================================")
    
    last_cpu_alert = 0
    last_battery_alert = 0
    
    # Ensure the cache folder exists for the dead-drop
    os.makedirs("audio_cache", exist_ok=True)
    
    while True:
        try:
            current_time = time.time()
            
            # 1. CHECK CPU LOAD (Spike above 90%)
            cpu_usage = psutil.cpu_percent(interval=1)
            if cpu_usage > 90 and (current_time - last_cpu_alert) > CPU_COOLDOWN:
                print(f"\n[Aegis] Critical CPU Spike detected: {cpu_usage}%")
                
                # Pre-calculated payloads to save RAM during a CPU spike
                phrases = [
                    f"Warning macha, CPU load is critical at {cpu_usage} percent. System is struggling.",
                    f"Bro, my processor is maxing out at {cpu_usage} percent. Pause your render.",
                    f"Careful macha, CPU is hitting {cpu_usage} percent. I recommend shutting down background apps."
                ]
                alert_text = random.choice(phrases)
                
                # Dead-drop the payload for wake_agent.py to speak
                with open("audio_cache/security_alert.json", "w") as f:
                    json.dump({"alert": alert_text}, f)
                notifier.queue_alert("aegis", alert_text, level="warning")
                    
                last_cpu_alert = current_time

            # 2. CHECK BATTERY LIFE (Drop below 20%)
            battery = psutil.sensors_battery()
            if battery:
                plugged = battery.power_plugged
                percent = battery.percent
                
                if not plugged and percent <= 20 and (current_time - last_battery_alert) > BATTERY_COOLDOWN:
                    print(f"\n[Aegis] Critical Battery Drop: {percent}%")
                    
                    phrases = [
                        f"Macha, battery is down to {percent} percent. Plug me in.",
                        f"Warning bro, system power is at {percent} percent. Find a charger fast.",
                        f"Power levels critical macha. We only have {percent} percent battery left."
                    ]
                    alert_text = random.choice(phrases)
                    
                    with open("audio_cache/security_alert.json", "w") as f:
                        json.dump({"alert": alert_text}, f)
                    notifier.queue_alert("aegis", alert_text, level="warning")
                        
                    last_battery_alert = current_time

            # Poll every 5 seconds (Effectively 0% background RAM usage)
            time.sleep(5) 
            
        except KeyboardInterrupt:
            print("\n[Shutting down Aegis Matrix...]")
            break
        except Exception as e:
            print(f"[Aegis Error]: {e}")
            time.sleep(10)

if __name__ == "__main__":
    start_aegis()