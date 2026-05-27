import json
import sqlite3
import urllib.request
import os

from app.services import handle_evolution_webhook

db_path = os.getenv("DB_PATH", "data/whatsapp_agent.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
base_url = os.getenv("EVOLUTION_BASE_URL", "http://evolution-api:8080").rstrip("/")
instance = os.getenv("EVOLUTION_INSTANCE", "whatsapp-pi-new")
api_key = os.getenv("EVOLUTION_API_KEY", "")

if not api_key:
    raise SystemExit("Missing EVOLUTION_API_KEY")

def fetch_messages_page(page, limit):
    req = urllib.request.Request(
        f"{base_url}/chat/findMessages/{instance}",
        data=json.dumps({"page": page, "limit": limit}).encode(),
        headers={"apikey": api_key, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def run():
    print("Fetching messages from Evolution API for the past 2 months...")
    import time
    page = 1
    limit = 500
    total_success = 0
    total_processed = 0
    
    while True:
        try:
            print(f"Fetching page {page}...")
            data = fetch_messages_page(page, limit)
            
            if isinstance(data, dict) and 'messages' in data:
                records = data['messages'].get('records', [])
                if not records:
                    print("No more records found.")
                    break
                
                print(f"Got {len(records)} messages on page {page}.")
                for record in records:
                    payload = {
                        "event": "messages.upsert",
                        "data": record
                    }
                    res = handle_evolution_webhook(payload)
                    total_processed += 1
                    if res.get("status") == "success":
                        total_success += 1
                
                page += 1
            else:
                print("Invalid response format.")
                break
        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break
            
    print(f"Import complete! Successfully imported {total_success} messages out of {total_processed} processed.")

if __name__ == "__main__":
    run()
