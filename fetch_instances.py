import json
import os
import urllib.request

base_url = os.getenv("EVOLUTION_PUBLIC_URL", os.getenv("EVOLUTION_BASE_URL", "http://127.0.0.1:8081")).rstrip("/")
api_key = os.getenv("EVOLUTION_API_KEY", "")
url = f"{base_url}/instance/fetchInstances"
headers = {
    "apikey": api_key,
    "Content-Type": "application/json"
}

if not api_key:
    raise SystemExit("Missing EVOLUTION_API_KEY")

print(f"Fetching instances from {url}...")
try:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error: {e}")
