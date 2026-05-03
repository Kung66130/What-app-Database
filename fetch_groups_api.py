import json
import urllib.request
import os

# ใช้ IP ของ Raspberry Pi ผ่าน Tailscale
url = "http://100.123.233.122:8081/group/fetchAllGroups/whatsapp-pi-new"
headers = {
    "apikey": "wa-agent-secret-key",
    "Content-Type": "application/json"
}

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
