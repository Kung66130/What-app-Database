import json
import sqlite3
import urllib.request
import os

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
        print(f"Got response. Status: {data.get('status')}")
    except Exception as e:
        print(f"Error fetching messages: {e}")

if __name__ == "__main__":
    run()
