"""OAuth2 authentication for YouTube Data API v3.

Two-account system:
  token_jt.json    -- etracyjob@gmail.com (Gavin's Google account) with access to @roll4veterans.
                      Used for all pipeline ops: push metadata, discover unlisted, add to playlist.
  token_gavin.json -- Gavin's @erictracy5584 account.
                      Used for Gavin's personal likes and replies during engage.

Note: etracyjob@gmail.com is GAVIN's account (not JT's). Gavin manages the @roll4veterans
channel on JT's behalf. The token grants API access to @roll4veterans.
"""
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config.settings import YOUTUBE_SCOPES, CLIENT_SECRET_FILE, TOKEN_FILE_JT, TOKEN_FILE_GAVIN


def get_youtube_service(token_file: Path | None = None, account_hint: str = "") -> object:
    """Return an authenticated YouTube Data API v3 service resource.

    Parameters
    ----------
    token_file : Path, optional
        Path to the token JSON file. Defaults to TOKEN_FILE_JT (JT's owner account).
        Pass TOKEN_FILE_GAVIN to use Gavin's manager account.
    account_hint : str, optional
        Shown in the first-time browser auth prompt so the user knows which
        Google account to sign in with (e.g. "etracyjob@gmail.com").

    On first run for a given token_file, opens a browser window for OAuth2
    consent and saves the token. Subsequent calls refresh automatically.
    """
    if token_file is None:
        token_file = TOKEN_FILE_JT
    token_file = Path(token_file)

    creds = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), YOUTUBE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as _refresh_err:
                print(f"[auth] Token refresh failed ({_refresh_err}) — re-authenticating via browser")
                creds = None  # fall through to browser flow below
        if not creds or not creds.valid:
            if not CLIENT_SECRET_FILE.exists():
                raise FileNotFoundError(
                    f"OAuth credentials not found at {CLIENT_SECRET_FILE}\n"
                    "Download client_secret.json from Google Cloud Console and place it in config/"
                )
            if account_hint:
                print(f"[auth] Opening browser — sign in as: {account_hint}")
            else:
                label = token_file.stem  # e.g. "token_jt"
                print(f"[auth] Opening browser for OAuth ({label})")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_FILE), YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=0, prompt="select_account consent")

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
        print(f"[auth] Token saved -> {token_file.name}")

    return build("youtube", "v3", credentials=creds)


def get_youtube_service_jt() -> object:
    """Return YouTube service authenticated via etracyjob@gmail.com targeting @roll4veterans.

    etracyjob@gmail.com is Gavin's Google account. It has owner/manager access to the
    @roll4veterans channel. Use for all pipeline operations: discover unlisted videos,
    push metadata, add to playlist.
    """
    return get_youtube_service(
        token_file=TOKEN_FILE_JT,
        account_hint="etracyjob@gmail.com (Gavin's account — grants access to @roll4veterans)",
    )


def get_youtube_service_gavin() -> object:
    """Return YouTube service authenticated as Gavin's @erictracy5584 account.

    Use for Gavin's personal engagement: likes and comment replies posted as @erictracy5584.
    """
    return get_youtube_service(
        token_file=TOKEN_FILE_GAVIN,
        account_hint="etracyjob@gmail.com / @erictracy5584 (Gavin's personal channel)",
    )
