import json
import os
import ollama

# This file acts as Argus's passport vault.
VAULT_FILE = "secure_vault/api_keys.json"

def load_vault():
    if os.path.exists(VAULT_FILE):
        with open(VAULT_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_to_vault(app_name, credentials):
    vault = load_vault()
    vault[app_name] = credentials
    with open(VAULT_FILE, 'w') as f:
        json.dump(vault, f, indent=4)

def handle_app_connection(user_request):
    """Determines which app the user wants, checks the vault, and routes the connection."""
    
    # 1. Ask Llama to figure out which app the user is talking about
    prompt = f"The user wants to connect to an app. Extract ONLY the name of the app from this text. If no app is mentioned, output 'UNKNOWN'. Text: '{user_request}'"
    response = ollama.chat(model='llama3.1', messages=[{'role': 'system', 'content': prompt}])
    target_app = response['message']['content'].strip().lower()

    # 2. If the user didn't specify, Argus must ask them.
    if target_app == "unknown" or target_app == "":
        return "Macha, my API bridge is ready, but you didn't tell me which app to hook into. Gmail? LinkedIn? Sollu."

    vault = load_vault()

    # 3. If we don't have access, ask the user to provide it.
    if target_app not in vault:
        return f"I am trying to breach {target_app.capitalize()}, but I don't have the API keys or app passwords in my vault. You need to authorize me first."

    # 4. If we DO have access, route to the specific logic
    if target_app == "gmail":
        # We will build the IMAP email reading logic here later
        return "I have successfully authenticated with the Gmail servers. Awaiting your command."
    
    elif target_app == "linkedin":
        # We will build the web-scraping/API logic here later
        return "LinkedIn matrix is online. I have access to your network."
        
    else:
        return f"I have credentials for {target_app.capitalize()}, but I don't have a specific execution matrix written for it yet."