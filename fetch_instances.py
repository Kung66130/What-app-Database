import json
import urllib.request

url = "http://100.123.233.122:8081/instance/fetchInstances"
headers = {
    "apikey": "wa-agent-secret-key",
    "Content-Type": "application/json"
}

print(f"Fetching instances from {url}...")
try:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error: {e}")
