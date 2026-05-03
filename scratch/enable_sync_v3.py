import requests

api_url = "http://localhost:8081"
api_key = "wa-agent-secret-key"
instance = "whatsapp-pi-new"

print(f"Setting settings for {instance}...")

settings = {
    "rejectCall": False,
    "groupsIgnore": True,
    "alwaysOnline": False,
    "readMessages": False,
    "readStatus": False,
    "syncFullHistory": True
}

try:
    res = requests.post(
        f"{api_url}/settings/set/{instance}",
        headers={"apikey": api_key, "Content-Type": "application/json"},
        json=settings
    )
    print(f"Status: {res.status_code}")
    print(f"Response: {res.text}")
except Exception as e:
    print(f"Error: {e}")
