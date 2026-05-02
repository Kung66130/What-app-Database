import json
import sqlite3
import urllib.request
import os

from app.services import handle_evolution_webhook

db_path = os.getenv("DB_PATH", "data/whatsapp_agent.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

def fetch_messages():
    req = urllib.request.Request(
        'http://evolution-api:8080/chat/findMessages/whatsapp-pi-new',
        data=json.dumps({"page": 1, "limit": 100}).encode(),
        headers={'apikey': 'wa-agent-secret-key', 'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def run():
    print("Fetching messages from Evolution API...")
    try:
        data = fetch_messages()
        if isinstance(data, dict) and 'messages' in data:
            records = data['messages'].get('records', [])
            print(f"Got {len(records)} messages. Importing...")
            success = 0
            for record in records:
                # Wrap it to look like a webhook payload
                payload = {
                    "event": "messages.upsert",
                    "data": record
                }
                res = handle_evolution_webhook(payload)
                if res.get("status") == "success":
                    success += 1
            print(f"Successfully imported {success} messages out of {len(records)}.")
        else:
            print("No messages found in response.")
    except Exception as e:
        print(f"Error fetching messages: {e}")

if __name__ == "__main__":
    run()
