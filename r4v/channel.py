"""Video discovery via yt-dlp (no API quota cost)."""
import json
import subprocess
import sys
from pathlib import Path
from config.settings import CHANNEL_URL, VIDEOS_JSON
from r4v.storage import load_json, save_json


def discover_videos(channel_url: str = CHANNEL_URL, force: bool = False) -> list[dict]:
    """Fetch all video metadata from the channel using yt-dlp.

    Returns a list of dicts with keys: id, title, url, upload_date, description.
    Results are cached in data/videos.json; pass force=True to re-fetch.
    """
    if not force and VIDEOS_JSON.exists():
        existing = load_json(VIDEOS_JSON) or []
        if existing:
            print(f"[channel] Loaded {len(existing)} videos from cache. Use --force to refresh.")
            return existing

    print(f"[channel] Discovering videos from {channel_url} ...")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        channel_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed:\n{result.stderr}")

    videos = []
    for line in result.stdout.strip().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        vid_id = entry.get("id", "")
        if not vid_id:
            continue
        videos.append({
            "id": vid_id,
            "title": entry.get("title", ""),
            "url": entry.get("url") or f"https://www.youtube.com/shorts/{vid_id}",
            "upload_date": entry.get("upload_date", ""),
            "description": entry.get("description", ""),
            "tags": entry.get("tags") or [],
            "duration": entry.get("duration"),
            "view_count": entry.get("view_count"),
        })

    save_json(VIDEOS_JSON, videos)
    print(f"[channel] Found {len(videos)} videos → saved to {VIDEOS_JSON}")
    return videos


def get_new_videos(channel_url: str = CHANNEL_URL) -> list[dict]:
    """Re-fetch and return only videos not already in cache."""
    existing_ids = {v["id"] for v in (load_json(VIDEOS_JSON) or [])}
    fresh = discover_videos(channel_url, force=True)
    new = [v for v in fresh if v["id"] not in existing_ids]
    if new:
        print(f"[channel] {len(new)} new video(s) found.")
    else:
        print("[channel] No new videos since last run.")
    return new
