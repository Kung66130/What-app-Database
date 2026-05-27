import json
import urllib.request
import os

base_url = os.getenv("EVOLUTION_PUBLIC_URL", os.getenv("EVOLUTION_BASE_URL", "http://127.0.0.1:8081")).rstrip("/")
instance = os.getenv("EVOLUTION_INSTANCE", "whatsapp-pi-new")
api_key = os.getenv("EVOLUTION_API_KEY", "")
url = f"{base_url}/group/fetchAllGroups/{instance}"
headers = {
    "apikey": api_key,
    "Content-Type": "application/json"
}

if not api_key:
    raise SystemExit("Missing EVOLUTION_API_KEY")

print(f"Fetching groups from {url}...")
try:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        
    if isinstance(data, list):
        print(f"Found {len(data)} groups.")
        for g in data:
            name = g.get("subject", "Unknown")
            jid = g.get("id", "")
            if "wax" in name.lower():
                print(f"MATCH FOUND: Name='{name}', JID='{jid}'")
    else:
        print("Unexpected response format:", data)
except Exception as e:
    print(f"Error: {e}")
