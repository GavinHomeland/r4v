"""OAuth2 authentication for YouTube Data API v3."""
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config.settings import YOUTUBE_SCOPES, CLIENT_SECRET_FILE, TOKEN_FILE


def get_youtube_service():
    """Return an authenticated YouTube Data API v3 service resource.

    On first run, opens a browser window for OAuth2 consent and saves
    the token to config/token.json. Subsequent calls refresh automatically.
    """
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), YOUTUBE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_FILE.exists():
                raise FileNotFoundError(
                    f"OAuth credentials not found at {CLIENT_SECRET_FILE}\n"
                    "Download client_secret.json from Google Cloud Console and place it in config/"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_FILE), YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)
