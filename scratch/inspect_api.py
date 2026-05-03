import sqlite3
import requests
import json
import time
import base64
import os
from pathlib import Path

db_path = "/home/admin/what-app-database/data/whatsapp_agent.db"
api_url = "http://localhost:8081"
api_key = "wa-agent-secret-key"
instance = "whatsapp-pi-new"
media_dir = "/home/admin/what-app-database/data/media"

print("Inspecting Evolution API response format...")

try:
    jid = "120363421828572274@g.us" # Using one of the JIDs from logs
    res = requests.post(
        f"{api_url}/chat/findMessages/{instance}",
        headers={"apikey": api_key, "Content-Type": "application/json"},
        json={"where": {"key": {"remoteJid": jid}}, "limit": 1}
    )
    print(f"Status: {res.status_code}")
    print(f"Response: {json.dumps(res.json(), indent=2)[:500]}")
    
except Exception as e:
    print(f"Error inspecting: {e}")
