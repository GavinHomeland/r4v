"""scanner.py — Standalone unlisted-video discovery tool.

Scans the authenticated channel's full uploads playlist for unlisted videos,
logs newly found IDs to a private 'Unlisted Discovery Log' YouTube playlist,
and optionally fetches per-video metadata via yt-dlp (using cookies.txt for auth).

Run: python scanner.py
Auth: config/client_secret.json + config/token.json (same OAuth setup as main r4v app)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv, set_key
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import googleapiclient.discovery

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT   = Path(__file__).parent
ENV_PATH       = PROJECT_ROOT / ".env"
CLIENT_SECRET  = PROJECT_ROOT / "config" / "client_secret.json"
TOKEN_PATH     = PROJECT_ROOT / "config" / "token.json"
COOKIES_FILE   = PROJECT_ROOT / "config" / "cookies.txt"

load_dotenv(ENV_PATH)

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


# ── OAuth2 ─────────────────────────────────────────────────────────────────────

def get_authenticated_service():
    """Return an authenticated YouTube API service.

    Uses token.json if valid; refreshes if expired; runs full browser OAuth
    flow via client_secret.json if no valid token exists.
    """
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET.exists():
                print(f"ERROR: {CLIENT_SECRET} not found.")
                print("Download OAuth credentials from Google Cloud Console and save there.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        print(f"[auth] Token saved → {TOKEN_PATH}")

    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)


# ── Log playlist ───────────────────────────────────────────────────────────────

def get_log_playlist(youtube) -> str:
    """Find or create a private 'Unlisted Discovery Log' playlist, return its ID."""
    env_id = os.getenv("TARGET_PLAYLIST_ID", "").strip()
    if env_id:
        return env_id

    print("[playlist] Searching for 'Unlisted Discovery Log' playlist...")
    req = youtube.playlists().list(part="snippet", mine=True, maxResults=50)
    while req:
        res = req.execute()
        for item in res.get("items", []):
            if item["snippet"]["title"] == "Unlisted Discovery Log":
                pid = item["id"]
                set_key(str(ENV_PATH), "TARGET_PLAYLIST_ID", pid)
                print(f"[playlist] Found existing log playlist: {pid}")
                return pid
        req = youtube.playlists().list_next(req, res)

    print("[playlist] Creating new 'Unlisted Discovery Log' playlist...")
    new_p = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {"title": "Unlisted Discovery Log"},
            "status": {"privacyStatus": "private"},
        },
    ).execute()
    pid = new_p["id"]
    set_key(str(ENV_PATH), "TARGET_PLAYLIST_ID", pid)
    print(f"[playlist] Created: {pid}")
    return pid


# ── Pagination helper ──────────────────────────────────────────────────────────

def paginate(youtube_resource, **kwargs) -> list:
    """Collect all items from a paginated YouTube API list call."""
    items = []
    page_token = None
    while True:
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube_resource.list(**kwargs).execute()
        items.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


# ── yt-dlp metadata fetch ──────────────────────────────────────────────────────

def fetch_ytdlp_info(video_id: str) -> dict | None:
    """Fetch video metadata via yt-dlp using cookies.txt for unlisted access.

    Returns parsed JSON info dict, or None on failure.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json",
        "--no-warnings",
        "--no-playlist",
    ]
    if COOKIES_FILE.exists():
        cmd += ["--cookies", str(COOKIES_FILE)]
    else:
        print(f"  [yt-dlp] Warning: {COOKIES_FILE} not found — unlisted videos may fail")
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0 or not result.stdout.strip():
        print(f"  [yt-dlp] Failed for {video_id}: {result.stderr[:200]}")
        return None
    try:
        return json.loads(result.stdout.strip().splitlines()[0])
    except Exception as e:
        print(f"  [yt-dlp] Parse error for {video_id}: {e}")
        return None


# ── Main scan ──────────────────────────────────────────────────────────────────

def run_scan(fetch_metadata: bool = True):
    youtube = get_authenticated_service()
    log_playlist_id = get_log_playlist(youtube)

    # 1. Uploads playlist ID — target the R4V channel by ID or handle
    channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
    if channel_id:
        print(f"[scan] Fetching channel info (id={channel_id})...")
        ch_resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    else:
        print("[scan] Fetching channel info (forHandle=@roll4veterans)...")
        ch_resp = youtube.channels().list(part="contentDetails", forHandle="@roll4veterans").execute()
    ch_items = ch_resp.get("items", [])
    if not ch_items:
        print("ERROR: Could not find R4V channel. Check YOUTUBE_CHANNEL_ID in .env")
        print("       or ensure the OAuth account has access to @roll4veterans.")
        sys.exit(1)
    uploads_id = ch_items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"[scan] Uploads playlist: {uploads_id}")

    # 2. Collect video IDs already in the log playlist (to skip duplicates)
    print("[scan] Loading existing log playlist entries...")
    log_items = paginate(
        youtube.playlistItems(),
        playlistId=log_playlist_id,
        part="snippet",
        maxResults=50,
    )
    existing_ids = {
        item["snippet"]["resourceId"]["videoId"]
        for item in log_items
    }
    print(f"[scan] Already logged: {len(existing_ids)} video(s)")

    # 3. Page through ALL uploads, collect video IDs
    print("[scan] Scanning full uploads playlist...")
    upload_items = paginate(
        youtube.playlistItems(),
        playlistId=uploads_id,
        part="contentDetails",
        maxResults=50,
    )
    all_upload_ids = [
        item["contentDetails"]["videoId"]
        for item in upload_items
    ]
    print(f"[scan] Total videos in uploads playlist: {len(all_upload_ids)}")

    # 4. Fetch status in batches of 50 and filter for unlisted
    print("[scan] Checking privacy status...")
    unlisted_ids = []
    for i in range(0, len(all_upload_ids), 50):
        batch = all_upload_ids[i:i + 50]
        resp = youtube.videos().list(part="status", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            if item["status"].get("privacyStatus") == "unlisted":
                unlisted_ids.append(item["id"])

    print(f"[scan] Unlisted videos found: {len(unlisted_ids)}")

    # 5. Filter to newly discovered ones
    new_ids = [vid for vid in unlisted_ids if vid not in existing_ids]
    print(f"[scan] New (not yet logged): {len(new_ids)}")

    if not new_ids:
        print("\n" + "=" * 40)
        print("SCAN COMPLETE: No new unlisted videos found.")
        print("=" * 40)
        return

    # 6. Add new IDs to the log playlist + optionally fetch yt-dlp metadata
    newly_logged = []
    for vid in new_ids:
        print(f"\n[scan] New unlisted: {vid}")

        # Add to log playlist
        try:
            youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": log_playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": vid},
                    }
                },
            ).execute()
            print(f"  Added to log playlist")
        except Exception as e:
            print(f"  Failed to add to playlist: {e}")

        # Fetch additional metadata via yt-dlp if requested
        if fetch_metadata:
            info = fetch_ytdlp_info(vid)
            if info:
                title    = info.get("title", "(no title)")
                duration = info.get("duration", 0)
                print(f"  Title:    {title}")
                print(f"  Duration: {duration}s")
                print(f"  URL:      https://www.youtube.com/watch?v={vid}")

        newly_logged.append(vid)

    # 7. Final report
    print("\n" + "=" * 40)
    print(f"SUCCESS: {len(newly_logged)} new unlisted video(s) found and logged.")
    print("IDs — paste these into review.pyw > Add Video, or run:")
    print("-" * 40)
    for vid in newly_logged:
        print(f"  python cli.py add-video {vid}")
    print("=" * 40)


if __name__ == "__main__":
    run_scan(fetch_metadata=True)
