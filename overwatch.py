import psutil
import time
import json
import os
import random
import notifier

# Ports we trust: Web (80, 443), DNS (53), Local FastAPI (8000), Local DBs (5432, 3306)
SAFE_PORTS = {80, 443, 53, 8000, 5432, 3306}
ALERT_COOLDOWN = 300  # Wait 5 minutes before warning about the same IP again

def start_overwatch():
    print("========================================")
    print("ARGUS OVERWATCH MATRIX: ONLINE")
    print("Packet sniper is active. Watching the grid...")
    print("========================================")
    
    os.makedirs("audio_cache", exist_ok=True)
    flagged_connections = {}

    while True:
        try:
            current_time = time.time()
            # Scan all IPv4 and IPv6 connections
            connections = psutil.net_connections(kind='inet')
            
            for conn in connections:
                # We only care about active, established connections
                if conn.status == 'ESTABLISHED':
                    lport = conn.laddr.port
                    raddr = conn.raddr
                    
                    if raddr:
                        rip = raddr.ip
                        rport = raddr.port
                        
                        # Filter out safe ports and local network traffic
                        if (rport not in SAFE_PORTS and 
                            lport not in SAFE_PORTS and 
                            not rip.startswith("127.") and 
                            not rip.startswith("192.168.")):
                            
                            alert_key = f"{rip}:{rport}"
                            
                            # Only alert if it's a new threat or cooldown has passed
                            if alert_key not in flagged_connections or (current_time - flagged_connections[alert_key]) > ALERT_COOLDOWN:
                                print(f"\n[Overwatch] Suspicious route detected -> IP: {rip} | Port: {rport}")
                                
                                phrases = [
                                    f"Warning macha, unauthorized outbound traffic detected heading to port {rport}. Check the grid.",
                                    f"Bro, my packet sniper just caught a weird connection to an external IP. Stay sharp.",
                                    f"Tactical alert macha. Unknown network activity detected. Should I kill the connection?"
                                ]
                                
                                alert_text = random.choice(phrases)
                                
                                # Dead-drop the payload for wake_agent.py to speak out loud
                                with open("audio_cache/security_alert.json", "w") as f:
                                    json.dump({"alert": alert_text}, f)
                                notifier.queue_alert("overwatch", alert_text, level="warning")
                                    
                                flagged_connections[alert_key] = current_time

            # Low RAM polling: sleep for 3 seconds between sweeps
            time.sleep(3) 
            
        except KeyboardInterrupt:
            print("\n[Shutting down Overwatch Matrix...]")
            break
        except Exception as e:
            print(f"[Overwatch Error]: {e}")
            time.sleep(5)

if __name__ == "__main__":
    start_overwatch()