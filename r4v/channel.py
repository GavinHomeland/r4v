"""Video discovery via yt-dlp (no API quota cost)."""
import json
import subprocess
import sys
from pathlib import Path
import re
from config.settings import CHANNEL_URL, VIDEOS_JSON, YOUTUBE_CHANNEL_ID, COOKIES_FILE, COOKIE_BROWSER
from r4v.storage import load_json, save_json


def discover_videos(channel_url: str = CHANNEL_URL, force: bool = False) -> list[dict]:
    """Fetch all video metadata from the channel using yt-dlp.

    Returns a list of dicts with keys: id, title, url, upload_date, description.
    Results are cached in data/videos.json; pass force=True to re-fetch.
    """
    # Load existing cache — used for early-return in non-force mode and for merging below
    existing = load_json(VIDEOS_JSON) or []
    if not force and existing:
        print(f"[channel] Loaded {len(existing)} videos from cache. Use --force to refresh.")
        return existing

    # Build lookup so we can preserve descriptions/tags fetched by fetch_descriptions
    existing_map = {v["id"]: v for v in existing}

    print(f"[channel] Discovering videos from {channel_url} ...")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
    ]
    # Inject auth so yt-dlp can see unlisted videos (logged in as @roll4veterans in Edge)
    if COOKIE_BROWSER and COOKIE_BROWSER.lower() != "none":
        cmd += ["--cookies-from-browser", COOKIE_BROWSER]
        print(f"[channel] Using cookies from {COOKIE_BROWSER} browser for auth")
    elif COOKIES_FILE.exists():
        cmd += ["--cookies", str(COOKIES_FILE)]
        print(f"[channel] Using cookies file for auth")
    cmd.append(channel_url)
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    _cookie_fail = result.returncode != 0 and any(
        s in result.stderr for s in ("Could not copy", "Failed to decrypt", "DPAPI")
    )
    if _cookie_fail:
        # Browser DB is locked (browser is open) — retry without auth cookies
        print("[channel] Browser cookie extraction failed (Edge is open/locked) — retrying without auth (unlisted videos may be missed)")
        cmd_no_auth = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "--dump-json", "--no-warnings", channel_url]
        result = subprocess.run(cmd_no_auth, capture_output=True, text=True, encoding="utf-8")
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
        cached = existing_map.get(vid_id, {})
        videos.append({
            "id": vid_id,
            "title": entry.get("title", ""),
            "url": entry.get("url") or f"https://www.youtube.com/shorts/{vid_id}",
            "upload_date": entry.get("upload_date", ""),
            # Prefer cached description — flat-playlist rarely includes full descriptions
            "description": entry.get("description", "") or cached.get("description", ""),
            "tags": entry.get("tags") if entry.get("tags") is not None else (cached.get("tags") or []),
            "duration": entry.get("duration") or cached.get("duration"),
            "view_count": entry.get("view_count") or cached.get("view_count"),
            "availability": entry.get("availability", "") or cached.get("availability", ""),
        })

    # Merge back cached videos not returned by yt-dlp (e.g. unlisted/private videos
    # added via discover-unlisted / YouTube API).  yt-dlp only sees the public channel
    # page, so we must not drop entries that were added through other means.
    yt_dlp_ids = {v["id"] for v in videos}
    preserved = [v for v in existing_map.values() if v["id"] not in yt_dlp_ids]
    if preserved:
        videos.extend(preserved)
        print(f"[channel] + {len(preserved)} cached unlisted/private video(s) preserved")

    save_json(VIDEOS_JSON, videos)
    print(f"[channel] Found {len(videos)} videos -> saved to {VIDEOS_JSON}")
    return videos


def fetch_descriptions(
    videos: list[dict] | None = None,
    skip_ids: set[str] | None = None,
) -> list[dict]:
    """Fetch full descriptions for videos where description is empty.

    Uses yt-dlp per-video (not flat-playlist) so descriptions are included.
    Updates and saves videos.json in-place. Returns the updated list.

    skip_ids: video IDs to skip (e.g. already-done videos).
    """
    if videos is None:
        loaded = load_json(VIDEOS_JSON)
        videos = loaded if isinstance(loaded, list) else []

    _skip = skip_ids or set()
    missing = [v for v in videos if not v.get("description") and v["id"] not in _skip]
    if not missing:
        print("[channel] All videos already have descriptions.")
        return videos

    print(f"[channel] Fetching descriptions for {len(missing)} videos ...")
    for i, v in enumerate(missing, 1):
        vid_id = v["id"]
        print(f"[channel] {i}/{len(missing)} {vid_id} ...", end=" ", flush=True)
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--dump-json", "--no-warnings",
            "--no-playlist",
            f"https://www.youtube.com/shorts/{vid_id}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0 or not result.stdout.strip():
            print("FAILED")
            continue
        try:
            info = json.loads(result.stdout.strip().splitlines()[0])
        except Exception:
            print("PARSE ERROR")
            continue
        desc = info.get("description", "")
        tags = info.get("tags") or []
        v["description"] = desc
        if tags and not v.get("tags"):
            v["tags"] = tags
        print(f"ok ({len(desc)} chars)")

    save_json(VIDEOS_JSON, videos)
    print(f"[channel] Saved updated videos.json")
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


def _parse_iso_duration(iso: str) -> int:
    """Parse ISO 8601 duration string (e.g. PT1M30S) into total seconds."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


_SHORTS_MAX_SECONDS = 200  # YouTube Shorts up to 3 min; API sometimes reports 181s for 3-min clips


def discover_unlisted_via_api(service) -> list[dict]:
    """Use the authenticated YouTube Data API to find unlisted/new Shorts.

    yt-dlp scrapes the public channel page and only sees public videos.
    This queries the channel's uploads playlist via the API, which returns everything
    the authenticated owner can see (public, unlisted, private).

    Only Shorts (duration ≤ 60 s) are added as new entries — regular videos on the
    channel are ignored.  Availability is still updated for all existing entries.
    Returns the full updated video list.
    """
    # 1. Get the uploads playlist ID for the @roll4veterans channel (not the OAuth user's channel)
    if YOUTUBE_CHANNEL_ID:
        resp = service.channels().list(part="contentDetails", id=YOUTUBE_CHANNEL_ID).execute()
    else:
        handle_match = re.search(r"/@([\w.-]+)", CHANNEL_URL)
        handle = f"@{handle_match.group(1)}" if handle_match else None
        if handle:
            resp = service.channels().list(part="contentDetails", forHandle=handle).execute()
        else:
            resp = service.channels().list(part="contentDetails", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        print("[channel] API: could not get channel info — check OAuth account")
        return load_json(VIDEOS_JSON) or []

    uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"[channel] API: uploads playlist = {uploads_id}")

    # 2. Page through playlistItems to collect all video IDs
    all_video_ids: list[str] = []
    page_token = None
    while True:
        kwargs: dict = {"playlistId": uploads_id, "part": "contentDetails", "maxResults": 50}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.playlistItems().list(**kwargs).execute()
        for item in resp.get("items", []):
            vid_id = item.get("contentDetails", {}).get("videoId")
            if vid_id:
                all_video_ids.append(vid_id)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    print(f"[channel] API: {len(all_video_ids)} total video IDs in uploads playlist")

    # 3. Fetch snippet+status+contentDetails in batches of 50
    api_data: dict[str, dict] = {}
    for i in range(0, len(all_video_ids), 50):
        batch = all_video_ids[i:i + 50]
        resp = service.videos().list(
            part="snippet,status,contentDetails", id=",".join(batch)
        ).execute()
        for item in resp.get("items", []):
            vid_id = item["id"]
            snippet = item.get("snippet", {})
            status = item.get("status", {})
            privacy = status.get("privacyStatus", "public")
            duration_sec = _parse_iso_duration(
                item.get("contentDetails", {}).get("duration", "")
            )
            live_broadcast = snippet.get("liveBroadcastContent", "none")
            api_data[vid_id] = {
                "id": vid_id,
                "title": snippet.get("title", ""),
                "url": f"https://www.youtube.com/shorts/{vid_id}",
                "upload_date": snippet.get("publishedAt", "")[:10].replace("-", ""),
                "description": snippet.get("description", ""),
                "tags": snippet.get("tags", []),
                "duration": duration_sec or None,
                "view_count": None,
                "availability": privacy,
                "_duration_sec": duration_sec,
                "_is_live": live_broadcast in ("live", "upcoming") or "is live" in snippet.get("title", "").lower(),
            }

    # 4. Merge: update availability on existing entries, add missing ones
    existing = load_json(VIDEOS_JSON) or []
    existing_map = {v["id"]: v for v in existing}

    # Video IDs that appeared in the playlist but had no metadata returned —
    # these are private, still processing, or deleted. Mark them so transcripts are skipped.
    invisible = [vid for vid in all_video_ids if vid not in api_data]
    if invisible:
        print(f"[channel] API: {len(invisible)} playlist ID(s) returned no metadata "
              f"(private / still processing / deleted):")
        for vid in invisible:
            print(f"  https://studio.youtube.com/video/{vid}/edit")
        for v in existing:
            if v["id"] in invisible:
                v["availability"] = "private"

    for v in existing:
        if v["id"] in api_data:
            v["availability"] = api_data[v["id"]]["availability"]

    from config.settings import TRANSCRIPTS_DIR, GENERATED_DIR

    # Stash durations and live flags before modifying api_data.
    api_durations: dict[str, int] = {
        vid_id: v.pop("_duration_sec", 0) for vid_id, v in api_data.items()
    }
    api_live: dict[str, bool] = {
        vid_id: v.pop("_is_live", False) for vid_id, v in api_data.items()
    }

    new_count = 0
    skipped_long = 0
    skipped_live = 0
    for vid_id, api_video in api_data.items():
        if vid_id not in existing_map:
            if api_live.get(vid_id):
                skipped_live += 1
                continue  # ignore live streams
            if api_durations.get(vid_id, 0) > _SHORTS_MAX_SECONDS:
                skipped_long += 1
                continue  # ignore non-Shorts
            existing.append(api_video)
            existing_map[vid_id] = api_video
            new_count += 1

    # Remove any non-Short or live-stream videos that slipped in before this filter.
    # Only removes entries with no transcript and no generated metadata (safe to drop).
    cleaned = 0
    kept = []
    for v in existing:
        vid_id = v["id"]
        has_transcript = (TRANSCRIPTS_DIR / f"{vid_id}.json").exists()
        has_generated = (GENERATED_DIR / f"{vid_id}_metadata.json").exists()
        if has_transcript or has_generated:
            kept.append(v)
            continue
        dur = api_durations.get(vid_id) or v.get("duration") or 0
        is_live = api_live.get(vid_id) or "is live" in v.get("title", "").lower()
        if dur > _SHORTS_MAX_SECONDS or is_live:
            cleaned += 1
            continue
        kept.append(v)
    existing = kept

    save_json(VIDEOS_JSON, existing)
    unlisted = sum(1 for v in existing if v.get("availability") == "unlisted")
    msg = f"[channel] API merge: {len(existing)} total, {new_count} new Shorts added, {unlisted} unlisted"
    excluded = skipped_long + skipped_live + cleaned
    if excluded:
        msg += f" ({excluded} excluded: {skipped_live} live, {skipped_long + cleaned} non-Shorts)"
    print(msg)
    return existing
