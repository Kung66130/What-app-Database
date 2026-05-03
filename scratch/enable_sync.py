import requests

api_url = "http://localhost:8081"
api_key = "wa-agent-secret-key"
instance = "whatsapp-pi-new"

print(f"Enabling history sync for {instance}...")

try:
    res = requests.post(
        f"{api_url}/instance/setSettings/{instance}",
        headers={"apikey": api_key, "Content-Type": "application/json"},
        json={"syncFullHistory": True, "syncHistory": True}
    )
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")
except Exception as e:
    print(f"Error: {e}")
