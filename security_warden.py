import psutil
import time
import os
import json
import notifier

# Configuration
SECURE_FOLDER = "secure_vault"
ALERT_FILE = "audio_cache/security_alert.json"
SCAN_INTERVAL = 5  # Check every 5 seconds

os.makedirs(SECURE_FOLDER, exist_ok=True)

def get_active_ports():
    """Returns a set of all currently listening network ports."""
    connections = psutil.net_connections(kind='inet')
    listening_ports = {conn.laddr.port for conn in connections if conn.status == 'LISTEN'}
    return listening_ports

def get_vault_state():
    """Returns a dictionary of files and their last modification times."""
    state = {}
    for filename in os.listdir(SECURE_FOLDER):
        filepath = os.path.join(SECURE_FOLDER, filename)
        if os.path.isfile(filepath):
            state[filename] = os.path.getmtime(filepath)
    return state

def start_warden():
    print("========================================")
    print("ARGUS SECURITY WARDEN: ONLINE")
    print(f"Monitoring network ports and '{SECURE_FOLDER}' directory...")
    print("========================================")
    
    # Establish the baseline "safe" state
    baseline_ports = get_active_ports()
    baseline_vault = get_vault_state()
    
    try:
        while True:
            time.sleep(SCAN_INTERVAL)
            
            # 1. Check for Network Anomalies
            current_ports = get_active_ports()
            new_ports = current_ports - baseline_ports
            
            if new_ports:
                port_list = ", ".join(map(str, new_ports))
                alert_msg = f"Security Alert. Unauthorized network activity detected. New listening ports opened on: {port_list}."
                print(f"\n[THREAT DETECTED] {alert_msg}")
                
                with open(ALERT_FILE, 'w') as f:
                    json.dump({"alert": alert_msg}, f)
                notifier.queue_alert("security_warden", alert_msg, level="critical")
                    
                # Update baseline so it doesn't alert infinitely
                baseline_ports = current_ports
                
            # 2. Check for File Tampering
            current_vault = get_vault_state()
            for filename, mtime in current_vault.items():
                if filename in baseline_vault and mtime > baseline_vault[filename]:
                    alert_msg = f"Security Alert. Unauthorized file modification detected in the secure vault. The file {filename} was just altered."
                    print(f"\n[THREAT DETECTED] {alert_msg}")
                    
                    with open(ALERT_FILE, 'w') as f:
                        json.dump({"alert": alert_msg}, f)
                    notifier.queue_alert("security_warden", alert_msg, level="critical")
                        
                    baseline_vault = current_vault
                    
            # Check for deleted files
            deleted_files = set(baseline_vault.keys()) - set(current_vault.keys())
            if deleted_files:
                for filename in deleted_files:
                    alert_msg = f"Security Alert. A file named {filename} was just deleted from the secure vault."
                    print(f"\n[THREAT DETECTED] {alert_msg}")
                    
                    with open(ALERT_FILE, 'w') as f:
                        json.dump({"alert": alert_msg}, f)
                    notifier.queue_alert("security_warden", alert_msg, level="critical")
                        
                baseline_vault = current_vault

    except KeyboardInterrupt:
        print("\n[Warden] Shutting down security matrix.")

if __name__ == "__main__":
    start_warden()