"""Central configuration loader for R4V automation."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Locate project root (parent of config/)
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── API credentials ────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
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
COOKIES_FILE = CONFIG_DIR / "cookies.txt"  # optional — export from browser to bypass IP bans

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

# ── Gemini AI ──────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash-lite"

# ── R4V brand content ──────────────────────────────────────────────────────────
FOOTER_TEMPLATE = """\


JOIN THE CONVERSATION 🔗 🤝 🔗
Have a story to share? Want to support veterans? Interested in the ride?

📱 @roll4veterans — Follow the mission across platforms:
   • Facebook: https://facebook.com/roll4veterans
   • Instagram: https://instagram.com/roll4veterans
   • TikTok: https://tiktok.com/@roll4veterans
   • YouTube: https://youtube.com/@roll4veterans

🌐 Official Hub: https://r4v.songseekers.org
   • Ride updates, route maps, and real-time tracking.

🦅 Team Red, White & Blue: https://teamrwb.org
   • Connecting veterans through physical and social activity.

🤝 Support & Donate:
   • Mission Fund: https://gofund.me/fdff623ca
   • Team RWB Donation: https://www.zeffy.com/en-US/team/roll-for-veterans
   • Volunteer (Team Bravo): https://r4v.songseekers.org/team-bravo

🚴 Follow the ride on Strava: https://strava.app.link/hW78V3J2u0b

{hashtags}"""

# Ensure data directories exist at import time
for _d in (DATA_DIR, TRANSCRIPTS_DIR, GENERATED_DIR, APPLIED_DIR):
    _d.mkdir(parents=True, exist_ok=True)
