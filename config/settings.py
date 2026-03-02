"""Central configuration loader for R4V automation."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Locate project root (parent of config/)
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── API credentials ────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
YOUTUBE_CHANNEL_ID: str = os.environ.get("YOUTUBE_CHANNEL_ID", "")

# ── File paths ─────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("R4V_DATA_DIR", PROJECT_ROOT / "data"))
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
GENERATED_DIR = DATA_DIR / "generated"
APPLIED_DIR = DATA_DIR / "applied"
VIDEOS_JSON = DATA_DIR / "videos.json"
QUOTA_LOG_JSON = DATA_DIR / "quota_log.json"

CONFIG_DIR = PROJECT_ROOT / "config"
CLIENT_SECRET_FILE = CONFIG_DIR / "client_secret.json"
TOKEN_FILE = CONFIG_DIR / "token.json"

# ── YouTube API ────────────────────────────────────────────────────────────────
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CHANNEL_URL = "https://www.youtube.com/@roll4veterans/shorts"

# Daily quota safety ceiling (YouTube gives 10,000 units/day; we stay under 9,500)
QUOTA_DAILY_LIMIT = 9_500
# Quota costs
QUOTA_VIDEOS_LIST = 1
QUOTA_VIDEOS_UPDATE = 50
QUOTA_COMMENTS_INSERT = 50
QUOTA_VIDEOS_RATE = 50

# ── Claude AI ──────────────────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-6"

# ── R4V brand content ──────────────────────────────────────────────────────────
FOOTER_TEMPLATE = """\

---
JOIN THE CONVERSATION
Have a story to share? Want to support veterans? Interested in the ride?
📱 FB/IG/TT/YT: @roll4veterans
🌐 Website: r4v.songseekers.org{extra_links}

{hashtags}"""

# Ensure data directories exist at import time
for _d in (DATA_DIR, TRANSCRIPTS_DIR, GENERATED_DIR, APPLIED_DIR):
    _d.mkdir(parents=True, exist_ok=True)
