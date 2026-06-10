"""
google_services.py — OAuth user-consent connector for Google Workspace APIs.

Connects Gmail, Drive, Sheets, Docs, Calendar, and Contacts (People) under a
single sign-in as your own Google account. This is separate from the project's
Vertex AI / Gemini access, which authenticates through gcloud Application
Default Credentials — see embeddings.py and run_pipeline.py.

One-time setup
--------------
1. In the GCP console (project morsegrid-team):
     APIs & Services > OAuth consent screen  -> configure (External, add your
       email as a Test user).
     APIs & Services > Credentials > Create credentials > OAuth client ID
       -> Application type: "Desktop app" -> download the JSON.
   Save that file as `credentials.json` in this project root.
2. Run:
     venv/Scripts/python.exe google_services.py
   A browser opens — sign in and grant access. The resulting token is cached to
   `token.json` (gitignored) and reused/refreshed automatically afterward.

Usage
-----
    from google_services import gmail, drive, sheets, docs, calendar, people
    profile = gmail().users().getProfile(userId="me").execute()

If you change SCOPES below, delete token.json and re-run so the new permissions
are granted.
"""
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

_ROOT = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(_ROOT, "credentials.json")
TOKEN_FILE = os.path.join(_ROOT, "token.json")

# Scopes for every Workspace service this project connects to. gmail.modify
# covers read + send + label changes (but not permanent delete); the rest are
# full read/write for their service.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/contacts",
]


def get_credentials() -> Credentials:
    """Return valid OAuth user credentials, running the consent flow if needed."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Missing {CREDENTIALS_FILE}. Create an OAuth 'Desktop app' "
                    "client in the GCP console (APIs & Services > Credentials) "
                    "and download it to the project root as credentials.json."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            # Fixed port so the redirect URI is stable. A "Desktop app" client
            # accepts any localhost port automatically; a "Web application"
            # client requires http://localhost:8765/ in its Authorized redirect URIs.
            creds = flow.run_local_server(port=8765)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def _service(name: str, version: str):
    return build(name, version, credentials=get_credentials(), cache_discovery=False)


def gmail():
    return _service("gmail", "v1")


def drive():
    return _service("drive", "v3")


def sheets():
    return _service("sheets", "v4")


def docs():
    return _service("docs", "v1")


def calendar():
    return _service("calendar", "v3")


def people():
    return _service("people", "v1")


if __name__ == "__main__":
    print("Connecting to Google Workspace (OAuth user consent)...")
    get_credentials()  # triggers the browser flow on first run
    profile = gmail().users().getProfile(userId="me").execute()
    print(f"  Connected as: {profile.get('emailAddress')}")
    print(f"  Token cached to: {TOKEN_FILE}")
    print("  Services available: gmail, drive, sheets, docs, calendar, people")
