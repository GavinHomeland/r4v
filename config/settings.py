"""Central configuration loader for R4V automation."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Locate project root (parent of config/)
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# -- API credentials -----------------------------------------------------------
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
YOUTUBE_CHANNEL_ID: str = os.environ.get("YOUTUBE_CHANNEL_ID", "")

# -- File paths ----------------------------------------------------------------
DATA_DIR = Path(os.environ.get("R4V_DATA_DIR", PROJECT_ROOT / "data"))
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
GENERATED_DIR = DATA_DIR / "generated"
APPLIED_DIR = DATA_DIR / "applied"
VIDEOS_JSON = DATA_DIR / "videos.json"
QUOTA_LOG_JSON = DATA_DIR / "quota_log.json"
TRANSCRIPT_LOG_JSONL = DATA_DIR / "transcript_log.jsonl"
GLOBAL_AI_NOTES_JSON = DATA_DIR / "global_ai_notes.json"

CONFIG_DIR = PROJECT_ROOT / "config"
CLIENT_SECRET_FILE = CONFIG_DIR / "client_secret.json"
# Two OAuth tokens - one per Google account:
TOKEN_FILE_JT    = CONFIG_DIR / "token_jt.json"    # JT's owner account - all pipeline ops
TOKEN_FILE_GAVIN = CONFIG_DIR / "token_gavin.json"  # Gavin's manager account - engage 
TOKEN_FILE       = TOKEN_FILE_JT                    # default / backward compat alias
COOKIES_FILE = CONFIG_DIR / "cookies.txt"  # optional - export from browser to bypass IP bans
# Browser to pull cookies from directly (edge/chrome/firefox). Used by yt-dlp for auth discovery.
# Set R4V_COOKIE_BROWSER=none to disable. Default: edge (logged in as @roll4veterans)
COOKIE_BROWSER = os.environ.get("R4V_COOKIE_BROWSER", "none")  # edge/chrome/firefox or none
PROXIES_FILE = PROJECT_ROOT / "Webshare 10 proxies.txt"  # ip:port:user:pass per line

# -- Whisper (local ASR fallback for videos with no YouTube captions) ----------
# Python interpreter that has faster-whisper installed.
# Set R4V_WHISPER_PYTHON env var to override (e.g. in .env).
_whisper_default = r"E:\venvs\whisperx_env_v1\Scripts\python.exe"
WHISPER_PYTHON = Path(os.environ.get("R4V_WHISPER_PYTHON", _whisper_default))
WHISPER_MODEL = os.environ.get("R4V_WHISPER_MODEL", "large-v3-turbo")  # tiny/base/small/medium[.en]/large-v3-turbo

# -- YouTube API ---------------------------------------------------------------
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CHANNEL_URL = "https://www.youtube.com/@roll4veterans/shorts"

# Daily quota safety ceiling (YouTube gives 10,000 units/day; we stay under 9,500)
QUOTA_DAILY_LIMIT = 9_500
# Quota costs
QUOTA_VIDEOS_LIST = 1
QUOTA_VIDEOS_UPDATE = 50
QUOTA_COMMENTS_INSERT = 50
QUOTA_VIDEOS_RATE = 50
QUOTA_PLAYLIST_INSERT = 50

# Roll for Veterans playlist (auto-add on push)
PLAYLIST_ID = "PLG7yc8aCZNOLs8YaIHFy-9INucGXIdWa2"

# -- Gemini AI -----------------------------------------------------------------
GEMINI_MODEL = "gemini-2.5-flash-lite"

# -- R4V brand content ---------------------------------------------------------
FOOTER_TEMPLATE = """


JOIN THE CONVERSATION \U0001f517 \U0001f91d \U0001f517
Have a story to share? Want to support veterans? Interested in the ride?

\U0001f4f1 @roll4veterans \u2014 Follow the mission across platforms:
   \u2022 Facebook: https://facebook.com/roll4veterans
   \u2022 Instagram: https://instagram.com/roll4veterans
   \u2022 TikTok: https://tiktok.com/@roll4veterans
   \u2022 YouTube: https://youtube.com/@roll4veterans

\U0001f310 Official Hub: https://r4v.songseekers.org
   \u2022 Ride updates, route maps, and real-time tracking.

\U0001f985 Team Red, White & Blue: https://teamrwb.org
   \u2022 Connecting veterans through physical and social activity.

\U0001f91d Support & Donate:
   \u2022 Mission Fund: https://gofund.me/fdff623ca
   \u2022 Team RWB Donation: https://www.zeffy.com/en-US/team/roll-for-veterans
   \u2022 Volunteer (Team Bravo): https://r4v.songseekers.org/team-bravo

\U0001f6b4 Follow the ride on Strava: https://strava.app.link/hW78V3J2u0b

{hashtags}"""

# Ensure data directories exist at import time
for _d in (DATA_DIR, TRANSCRIPTS_DIR, GENERATED_DIR, APPLIED_DIR):
    _d.mkdir(parents=True, exist_ok=True)
