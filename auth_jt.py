"""YouTube auth for JT — called by RunMe.bat. Not meant to be run directly."""
import sys
from pathlib import Path

here = Path(__file__).parent

# Look for client_secret.json here or in config/
secret_file = here / "config" / "client_secret.json"
if not secret_file.exists():
    secret_file = here / "client_secret.json"
if not secret_file.exists():
    print("  ERROR: client_secret.json not found.")
    print("  Text Gavin — he needs to include that file.")
    sys.exit(1)

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("  ERROR: Required packages not installed.")
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), SCOPES)
creds = flow.run_local_server(port=0, prompt="select_account consent")

token_file = here / "token_jt.json"
token_file.write_text(creds.to_json(), encoding="utf-8")
