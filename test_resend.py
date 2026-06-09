import os, requests
from dotenv import load_dotenv
load_dotenv()

api_key   = os.getenv("RESEND_API_KEY")
from_addr = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
to_addr   = os.getenv("DEMO_TO_EMAIL", "faiyaz@systro.ai")

print(f"FROM : {from_addr}")
print(f"TO   : {to_addr}")
print(f"KEY  : {api_key[:10]}...")

resp = requests.post(
    "https://api.resend.com/emails",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={
        "from": from_addr,
        "to": [to_addr],
        "subject": "Resend test — Morsegrid pipeline",
        "html": "<p>If you see this, Resend is working.</p>",
    },
    timeout=15,
)

print(f"\nHTTP {resp.status_code}")
print(resp.json())
