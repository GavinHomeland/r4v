"""Transcript fetching and processing via youtube-transcript-api."""
import re
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

from config.settings import TRANSCRIPTS_DIR
from r4v.storage import load_json, save_json

# Regex for URLs mentioned in transcript text
_URL_RE = re.compile(r"https?://[^\s\"'>)]+")


def fetch_transcript(video_id: str, force: bool = False) -> dict | None:
    """Fetch and cache the transcript for a single video.

    Returns a dict with keys: video_id, text (full joined), segments (raw list), urls.
    Returns None if no transcript is available.
    """
    cache_path = TRANSCRIPTS_DIR / f"{video_id}.json"
    if not force and cache_path.exists():
        return load_json(cache_path)

    try:
        api = YouTubeTranscriptApi()
        segments = api.fetch(video_id)
        # segments is a FetchedTranscript object; iterate it to get dicts
        seg_list = [{"text": s.text, "start": s.start, "duration": s.duration} for s in segments]
    except (TranscriptsDisabled, NoTranscriptFound) as e:
        print(f"[transcript] No transcript for {video_id}: {e}")
        return None
    except Exception as e:
        print(f"[transcript] Error fetching {video_id}: {e}")
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
    """Fetch transcripts for a list of video IDs. Returns {video_id: transcript_data}."""
    results = {}
    for i, vid in enumerate(video_ids, 1):
        print(f"[transcript] {i}/{len(video_ids)} {vid}")
        results[vid] = fetch_transcript(vid, force=force)
    return results
