"""Transcript fetching and processing via youtube-transcript-api."""
import re
import time
import random
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

from config.settings import TRANSCRIPTS_DIR, COOKIES_FILE
from r4v.storage import load_json, save_json

# Regex for URLs mentioned in transcript text
_URL_RE = re.compile(r"https?://[^\s\"'>)]+")

# Delay between live fetches (seconds) — longer = less likely to trigger IP ban
_MIN_DELAY = 5.0
_MAX_DELAY = 10.0

# Retry logic on IP block (per-video)
_MAX_RETRIES = 3
_RETRY_WAIT = 20  # seconds to wait between per-video retries

# IP ban recovery — when consecutive blocks detected, wait this long before resuming
_BAN_WAIT_MINUTES = 120   # 2 hours
_MAX_BAN_WAITS = 6        # give up after 6 bans (12 hours total)


def _make_api() -> YouTubeTranscriptApi:
    """Return a YouTubeTranscriptApi instance, using cookies if available."""
    if COOKIES_FILE.exists():
        return YouTubeTranscriptApi(cookies=str(COOKIES_FILE))
    return YouTubeTranscriptApi()


def fetch_transcript(video_id: str, force: bool = False) -> dict | None:
    """Fetch and cache the transcript for a single video.

    Returns a dict with keys: video_id, text (full joined), segments (raw list), urls.
    Returns None if no transcript is available.
    """
    cache_path = TRANSCRIPTS_DIR / f"{video_id}.json"
    if not force and cache_path.exists():
        return load_json(cache_path)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            api = _make_api()
            segments = api.fetch(video_id)
            seg_list = [{"text": s.text, "start": s.start, "duration": s.duration} for s in segments]
            break  # success
        except (TranscriptsDisabled, NoTranscriptFound):
            print(f"[transcript] No transcript for {video_id}: subtitles unavailable")
            return None
        except Exception as e:
            msg = str(e)
            if "blocking" in msg.lower() or "ip" in msg.lower() or "RequestBlocked" in msg or "IpBlocked" in msg:
                if attempt < _MAX_RETRIES:
                    wait = _RETRY_WAIT * attempt
                    print(f"[transcript] IP blocked on {video_id}, waiting {wait}s (attempt {attempt}/{_MAX_RETRIES})")
                    time.sleep(wait)
                    continue
            print(f"[transcript] Error fetching {video_id}: {e}")
            return None
    else:
        print(f"[transcript] Gave up on {video_id} after {_MAX_RETRIES} attempts")
        return None

    full_text = " ".join(s["text"] for s in seg_list)
    full_text = re.sub(r"\s+", " ", full_text).strip()

    data = {
        "video_id": video_id,
        "text": full_text,
        "segments": seg_list,
        "urls": extract_urls(full_text),
    }
    save_json(cache_path, data)
    return data


def extract_text(transcript_data: dict) -> str:
    """Return the full joined transcript text."""
    return transcript_data.get("text", "")


def extract_urls(text: str) -> list[str]:
    """Return a deduplicated list of URLs found in transcript text."""
    found = _URL_RE.findall(text)
    seen = set()
    out = []
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def fetch_all_transcripts(video_ids: list[str], force: bool = False) -> dict[str, dict | None]:
    """Fetch transcripts for a list of video IDs with polite delays between requests.

    Stops early if an IP ban is detected — no point retrying every video.
    """
    using_cookies = COOKIES_FILE.exists()
    if using_cookies:
        print(f"[transcript] Using cookies from {COOKIES_FILE}")
    else:
        print("[transcript] No cookies file found - fetching anonymously (may hit IP limits)")

    results = {}
    total = len(video_ids)
    consecutive_blocks = 0
    ban_waits = 0

    for i, vid in enumerate(video_ids, 1):
        # Skip already-cached (no delay needed)
        cache_path = TRANSCRIPTS_DIR / f"{vid}.json"
        if not force and cache_path.exists():
            results[vid] = load_json(cache_path)
            print(f"[transcript] {i}/{total} {vid} (cached)")
            continue

        print(f"[transcript] {i}/{total} {vid}")
        result = fetch_transcript(vid, force=force)
        results[vid] = result

        if result is None:
            consecutive_blocks += 1
            if consecutive_blocks >= 2:
                ban_waits += 1
                if ban_waits > _MAX_BAN_WAITS:
                    print(f"[transcript] Reached max ban waits ({_MAX_BAN_WAITS}). Stopping.")
                    break
                print(
                    f"[transcript] IP ban detected (ban {ban_waits}/{_MAX_BAN_WAITS}) — "
                    f"sleeping {_BAN_WAIT_MINUTES} min then resuming..."
                )
                time.sleep(_BAN_WAIT_MINUTES * 60)
                consecutive_blocks = 0
        else:
            consecutive_blocks = 0

        # Polite delay only between live fetches, with jitter
        if i < total:
            delay = random.uniform(_MIN_DELAY, _MAX_DELAY)
            time.sleep(delay)

    return results
