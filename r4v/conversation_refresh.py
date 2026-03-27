"""Conversation refresh — periodic comment follow-ups on recent videos.

Every 3 days (date.day % 3 == 0), review.pyw prompts the user to run this.
Selects half of the videos pushed in the last 15 days, generates a natural
continuation comment from Gemini based on existing comments, then presents
each for review/edit before posting.

Account logic for generated follow-up:
  - If last comment is from @roll4veterans  → Gavin replies
  - If last comment is from @erictracy5584  → JT replies
  - If last comment is from neither         → JT replies
"""
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.errors import HttpError
from config.settings import (
    APPLIED_DIR, GENERATED_DIR, GEMINI_MODEL, GEMINI_API_KEY, QUOTA_VIDEOS_LIST,
)
from r4v import quota_tracker
from r4v.storage import load_json

# YouTube channel handle for each account (used to identify last commenter)
HANDLE_JT    = "@roll4veterans"
HANDLE_GAVIN = "@erictracy5584"


def should_suggest_refresh(override: bool = False) -> bool:
    """Return True if today is a refresh day (day-of-month % 3 == 0)."""
    if override:
        return True
    return datetime.now().day % 3 == 0


def get_recently_pushed_video_ids(days: int = 15) -> list[str]:
    """Return video IDs whose applied/ file was written in the last `days` days."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    result = []
    for p in APPLIED_DIR.glob("*_applied.json"):
        vid = p.stem.replace("_applied", "")
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                result.append(vid)
        except OSError:
            pass
    return result


def select_refresh_candidates(video_ids: list[str]) -> list[str]:
    """Return a random half of the given video IDs."""
    if not video_ids:
        return []
    n = max(1, len(video_ids) // 2)
    return random.sample(video_ids, min(n, len(video_ids)))


def fetch_video_comments(service, video_id: str, max_results: int = 10) -> list[dict]:
    """Fetch the most recent top-level comments for a video via YouTube API.

    Returns a list of dicts: [{author, text, published}] newest-first.
    Returns [] if comments are disabled or an error occurs.
    """
    try:
        quota_tracker.check_quota(QUOTA_VIDEOS_LIST)
        resp = service.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=max_results,
            order="time",
            textFormat="plainText",
        ).execute()
        quota_tracker.consume(QUOTA_VIDEOS_LIST, f"commentThreads.list({video_id})")
        comments = []
        for item in resp.get("items", []):
            snip = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "author":    snip.get("authorDisplayName", ""),
                "text":      snip.get("textDisplay", ""),
                "published": snip.get("publishedAt", ""),
                "thread_id": item["id"],  # top-level comment ID — used as parentId for replies
            })
        return comments
    except HttpError as e:
        if e.resp.status == 403:
            print(f"  [refresh] Comments disabled for {video_id}")
        else:
            print(f"  [refresh] Error fetching comments for {video_id}: {e}")
        return []


def _last_account(comments: list[dict]) -> str:
    """Determine which account posted the most recent comment."""
    if not comments:
        return "other"
    last_author = comments[0].get("author", "").lower()
    if "roll4veterans" in last_author:
        return "jt"
    if "erictracy" in last_author or "erictracy5584" in last_author:
        return "gavin"
    return "other"


def generate_refresh_comment(
    video_id: str,
    existing_comments: list[dict],
    responder: str,
    fresh_start: bool = False,
) -> str:
    """Use Gemini to generate a natural conversation follow-up comment.

    responder: "jt" or "gavin"
    existing_comments: last 3 comments, newest first
    fresh_start: True when there are no existing comments — JT is opening the thread cold
    Returns the generated comment text, or "" on failure.
    """
    if not GEMINI_API_KEY:
        return ""

    from google.genai import types
    from r4v.content_gen import _get_client, _build_system_prompt

    # Pull video title if available
    meta = load_json(GENERATED_DIR / f"{video_id}_metadata.json") or {}
    title = meta.get("title", video_id)

    # Build context from last 3 comments (reverse to chronological order)
    context_lines = []
    for c in reversed(existing_comments[:3]):
        context_lines.append(f"{c['author']}: {c['text']}")
    context = "\n".join(context_lines)

    if responder == "jt":
        if fresh_start:
            voice_instruction = (
                "Write a fresh comment from JT Tracy (@roll4veterans) — he's checking back in on "
                "this video. No greeting, no opener — just launch straight into a reaction or thought. "
                "Keep it short (1-3 sentences), warm, personal. Reference the video title. "
                "NEVER reply to a comment by the same account (@roll4veterans)."
            )
        else:
            voice_instruction = (
                "Write in JT Tracy's voice (@roll4veterans). "
                "No greeting, no opener — just dive right in. "
                "Keep it short (1-3 sentences), warm, personal. "
                "If anyone asked a question in the conversation above, answer it. "
                "Reference what was actually said in the conversation above. "
                "NEVER reply to a comment by the same account (@roll4veterans)."
            )
    else:
        voice_instruction = (
            "Write in Gavin's voice (@erictracy5584). Gavin is JT's actual brother. "
            "No greeting, no opener — just dive straight into a reply. "
            "Keep it short (1-2 sentences), warm, slightly goofy. "
            "If anyone asked a question in the conversation above, answer it. "
            "Reference what was actually said in the conversation above. "
            "Optionally append a non-sequitur life hack. "
            "NEVER reply to a comment by the same account (@erictracy5584)."
        )

    if fresh_start and not context:
        prompt = (
            f"Video: \"{title}\"\n\n"
            f"No comments yet on this video. {voice_instruction}\n\n"
            "Respond with ONLY the comment text — no quotes, no labels, no explanation."
        )
    else:
        prompt = (
            f"Video: \"{title}\"\n\n"
            f"Recent comment thread (chronological):\n{context}\n\n"
            f"Write the NEXT comment in this thread. {voice_instruction}\n\n"
            "Respond with ONLY the comment text — no quotes, no labels, no explanation."
        )

    try:
        response = _get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_build_system_prompt(),
                temperature=0.85,
            ),
        )
        return response.text.strip()
    except Exception as e:
        print(f"  [refresh] Gemini error for {video_id}: {e}")
        return ""


_GEMINI_POLITE_DELAY = 2  # seconds between Gemini calls (free tier ~15 RPM)


def prepare_refresh_batch(
    service_jt,
    video_ids: list[str],
    progress_callback=None,
) -> list[dict]:
    """Fetch comments and generate follow-ups for a batch of videos.

    Returns list of dicts ready for the review UI:
    [{video_id, title, existing_comments, responder, generated_comment}]
    Skips videos where comments are disabled or generation fails.

    progress_callback(current, total, status_text) — called after each video.
    """
    results = []
    total = len(video_ids)
    for i, vid in enumerate(video_ids, 1):
        meta = load_json(GENERATED_DIR / f"{vid}_metadata.json") or {}
        title = meta.get("title", vid)
        print(f"  [refresh] {i}/{total} {vid} — {title[:50]}")

        if progress_callback:
            progress_callback(i, total, f"({i}/{total}) Fetching comments — {title[:40]}")

        comments = fetch_video_comments(service_jt, vid)
        if not comments:
            # No comments yet — generate JT opener, then Gavin reply (two passes)
            print(f"    No comments — generating JT opener + Gavin reply pair")
            if progress_callback:
                progress_callback(i, total, f"({i}/{total}) No comments — generating JT opener — {title[:30]}")

            jt_text = generate_refresh_comment(vid, [], "jt", fresh_start=True)
            if not jt_text:
                print(f"    Skipped — JT generation failed")
                if i < total:
                    time.sleep(_GEMINI_POLITE_DELAY)
                continue

            time.sleep(_GEMINI_POLITE_DELAY)
            if progress_callback:
                progress_callback(i, total, f"({i}/{total}) Generating Gavin reply — {title[:30]}")

            fake_jt = {"author": HANDLE_JT, "text": jt_text, "published": "", "thread_id": ""}
            gavin_text = generate_refresh_comment(vid, [fake_jt], "gavin")

            results.append({
                "video_id":            vid,
                "title":               title,
                "existing_comments":   [],
                "responder":           "jt",
                "generated_comment":   jt_text,
                "reply_to_thread_id":  "",
                "reply_to_author":     "",
                "pair_with_next":      bool(gavin_text),
            })
            if gavin_text:
                results.append({
                    "video_id":            vid,
                    "title":               title,
                    "existing_comments":   [fake_jt],
                    "responder":           "gavin",
                    "generated_comment":   gavin_text,
                    "reply_to_thread_id":  "",
                    "reply_to_author":     HANDLE_JT,
                    "reply_to_jt_pending": True,
                })
            if i < total:
                time.sleep(_GEMINI_POLITE_DELAY)
            continue

        last = _last_account(comments)
        responder = "gavin" if last == "jt" else "jt"
        print(f"    Last commenter: {last} → {responder} will respond")

        if progress_callback:
            progress_callback(i, total, f"({i}/{total}) Generating reply ({responder.upper()}) — {title[:30]}")

        generated = generate_refresh_comment(vid, comments, responder)
        if not generated:
            print(f"    Skipped — generation failed")
            continue

        results.append({
            "video_id":           vid,
            "title":              title,
            "existing_comments":  comments[:3],
            "responder":          responder,
            "generated_comment":  generated,
            "reply_to_thread_id": comments[0].get("thread_id"),  # reply to most recent comment
            "reply_to_author":    comments[0].get("author", ""),
        })

        if i < total:
            time.sleep(_GEMINI_POLITE_DELAY)

    return results


def post_refresh_comment(
    service_jt,
    service_gavin,
    video_id: str,
    comment_text: str,
    responder: str,
    reply_to_thread_id: str = "",
    dry_run: bool = False,
) -> str | None:
    """Post the approved refresh comment as the correct account.

    Returns the thread_id on success (new top-level) or the reply_to_thread_id
    on success (reply), so callers can chain a paired Gavin reply.
    Returns None on failure.
    """
    from r4v.engagement import _post_top_level, _post_reply
    service = service_jt if responder == "jt" else service_gavin
    if service is None:
        print(f"  [refresh] No service for responder={responder}, skipping {video_id}")
        return None
    label = HANDLE_JT if responder == "jt" else HANDLE_GAVIN
    if reply_to_thread_id:
        ok = _post_reply(service, reply_to_thread_id, comment_text, label, dry_run)
        return reply_to_thread_id if ok else None
    return _post_top_level(service, video_id, comment_text, label, dry_run)
