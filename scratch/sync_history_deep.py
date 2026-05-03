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

print("Starting deep history sync script...")

def save_image(jid, msg_id, b64_data):
    try:
        filename = f"{msg_id}_{int(time.time())}.jpg"
        full_path = Path(media_dir) / filename
        with open(full_path, "wb") as f:
            f.write(base64.b64decode(b64_data))
        return f"media/{filename}"
    except Exception as e:
        print(f"Error saving image: {e}")
        return None

try:
    conn = sqlite3.connect(db_path)
    # Get groups that are JIDs
    groups = conn.execute("SELECT group_name FROM groups").fetchall()
    
    for (name,) in groups:
        jid = name
        if not ("@g.us" in jid or "@s.whatsapp.net" in jid):
            if name.isdigit() or "-" in name:
                 jid = f"{name}@g.us"
            else:
                 continue

        print(f"Deep syncing {jid}...")
        try:
            # 1. Find messages
            res = requests.post(
                f"{api_url}/chat/findMessages/{instance}",
                headers={"apikey": api_key, "Content-Type": "application/json"},
                json={"where": {"key": {"remoteJid": jid}}, "limit": 100}
            )
            
            if res.status_code != 200:
                print(f"Failed to find messages for {jid}: {res.status_code}")
                continue
                
            messages = res.json()
            # Handle different response formats (Evolution API v2 might return a list or an object)
            if isinstance(messages, dict) and "records" in messages:
                messages = messages["records"]
            elif isinstance(messages, dict) and "messages" in messages:
                 messages = messages["messages"]
            
            if not isinstance(messages, list):
                print(f"Unexpected response format for {jid}")
                continue

            for msg in messages:
                msg_id = msg.get("key", {}).get("id")
                # Check if it's an image
                if "imageMessage" in msg.get("message", {}):
                    print(f"Found image in {jid}, msg_id: {msg_id}")
                    # 2. Get Base64
                    try:
                        b64_res = requests.post(
                            f"{api_url}/message/getBase64/{instance}",
                            headers={"apikey": api_key, "Content-Type": "application/json"},
                            json={"key": {"id": msg_id, "remoteJid": jid}}
                        )
                        if b64_res.status_code == 200:
                            b64_data = b64_res.json().get("base64")
                            if b64_data:
                                path = save_image(jid, msg_id, b64_data)
                                if path:
                                    # 3. Update DB
                                    conn.execute("UPDATE messages SET media_path = ? WHERE source_hash = ?", (path, msg_id))
                                    conn.commit()
                                    print(f"Saved and linked image for {msg_id}")
                    except Exception as e:
                        print(f"Error fetching base64 for {msg_id}: {e}")
                time.sleep(0.5) # Prevent overloading

        except Exception as e:
            print(f"Error deep syncing {jid}: {e}")

    conn.close()
    print("Deep history sync completed.")
except Exception as e:
    print(f"Main script error: {e}")
