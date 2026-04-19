"""OAuth 2.0 flow helpers for Google Calendar."""
import os
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Read-write access to calendar events
SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "token.json"


def get_credentials() -> Credentials:
    """Return valid OAuth credentials, refreshing or re-authorising as needed.

    On first run this opens a browser window for Google consent.
    After that, token.json is reused and silently refreshed.
    """
    creds: Credentials | None = None
    credentials_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google OAuth token.")
            creds.refresh(Request())
        else:
            logger.info("Starting Google OAuth consent flow.")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
        logger.info("OAuth token saved to %s", TOKEN_FILE)

    return creds
