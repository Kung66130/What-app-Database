import sqlite3
import requests
import json
import time
import re

db_path = "/home/admin/what-app-database/data/whatsapp_agent.db"
api_url = "http://localhost:8081"
api_key = "wa-agent-secret-key"
instance = "whatsapp-pi-new"

print("Starting history sync script (v3 - findMessages)...")

try:
    conn = sqlite3.connect(db_path)
    groups = conn.execute("SELECT group_name FROM groups").fetchall()
    conn.close()
    
    jids_to_sync = []
    for (name,) in groups:
        if re.match(r"^\d+$", name) or "-" in name:
            if "@" not in name:
                jids_to_sync.append(f"{name}@g.us")
            else:
                jids_to_sync.append(name)

    print(f"Found {len(jids_to_sync)} JIDs to sync.")

    for jid in jids_to_sync:
        print(f"Requesting messages for {jid}...")
        try:
            # Evolution API v2 uses /chat/findMessages
            res = requests.post(
                f"{api_url}/chat/findMessages/{instance}",
                headers={"apikey": api_key, "Content-Type": "application/json"},
                json={"where": {"key": {"remoteJid": jid}}, "limit": 100}
            )
            print(f"Result for {jid}: {res.status_code}")
            # The API call itself might trigger the webhook for each message found
            time.sleep(2)
        except Exception as e:
            print(f"Error syncing {jid}: {e}")

    print("History sync request completed.")
except Exception as e:
    print(f"Main script error: {e}")
