"""AI-powered metadata generation using Claude API."""
import json
import re
import anthropic

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL, GENERATED_DIR, FOOTER_TEMPLATE
from r4v.storage import load_json, save_json

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


SYSTEM_PROMPT = """\
You are a social media content specialist for Roll4Veterans (R4V), a 4,463-mile \
cross-country bicycle journey from Key West, FL to Los Angeles, CA to Flagstaff, AZ \
(Feb 27 – Jun 21, 2026) supporting veterans through Team Red, White & Blue (Team RWB). \
The rider is Marcus Antonius.

Voice: authentic, inspiring, community-focused, grassroots. \
Never commercial or preachy. Write like a veteran who loves riding and loves people. \
Shorts are 60 seconds or less — content is raw, real, and on the road.

Team RWB (teamrwb.org) empowers veterans through physical and social activity. \
R4V social: @roll4veterans on FB/IG/TT/YT. Website: r4v.songseekers.org"""

USER_PROMPT_TMPL = """\
Given this YouTube Short transcript from the R4V channel, generate optimized metadata.

EXISTING TITLE: {existing_title}
TRANSCRIPT:
{transcript_text}

Generate the following and respond ONLY with valid JSON (no markdown, no extra text):
{{
  "title": "Punchy YouTube Short title, max 60 chars, action-oriented, includes R4V or veteran angle",
  "description": "3-4 engaging sentences summarizing the video. Authentic voice. No hashtags here.",
  "tags": ["15-20 YouTube tags", "mix of broad cycling/veteran tags and specific content tags"],
  "hashtags": "#RollForVeterans #R4V and 10-14 more hashtags specific to this video's content",
  "comment": "One authentic comment (1-2 sentences) to post as the channel owner — mission-aligned, invites engagement"
}}"""


def _build_footer(hashtags: str, urls: list[str]) -> str:
    extra = ""
    if urls:
        extra = "\n" + "\n".join(f"🔗 {u}" for u in urls)
    return FOOTER_TEMPLATE.format(extra_links=extra, hashtags=hashtags)


def generate_metadata(
    video_id: str,
    transcript_text: str,
    existing_title: str = "",
    transcript_urls: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Generate AI metadata for a video. Caches result in data/generated/{video_id}_metadata.json.

    Returns the full metadata dict including footer-appended description.
    """
    cache_path = GENERATED_DIR / f"{video_id}_metadata.json"
    if not force and cache_path.exists():
        cached = load_json(cache_path)
        if cached and cached.get("title"):
            return cached

    client = _get_client()
    prompt = USER_PROMPT_TMPL.format(
        existing_title=existing_title or "(none)",
        transcript_text=transcript_text[:4000],  # stay within reasonable token budget
    )

    print(f"[content_gen] Generating metadata for {video_id} ...")
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        generated = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON for {video_id}: {e}\nRaw: {raw}")

    # Build full description with footer
    base_desc = generated.get("description", "")
    hashtags = generated.get("hashtags", "")
    footer = _build_footer(hashtags, transcript_urls or [])
    full_description = base_desc + footer

    result = {
        "video_id": video_id,
        "existing_title": existing_title,
        "title": generated.get("title", existing_title),
        "description": full_description,
        "description_base": base_desc,
        "tags": generated.get("tags", []),
        "hashtags": hashtags,
        "comment": generated.get("comment", ""),
        "approved": None,  # None = pending review; True = approved; False = skipped
    }
    save_json(cache_path, result)
    return result


def generate_all(videos: list[dict], transcripts: dict, force: bool = False) -> dict[str, dict]:
    """Generate metadata for all videos. Returns {video_id: metadata}."""
    results = {}
    total = len(videos)
    for i, video in enumerate(videos, 1):
        vid = video["id"]
        t_data = transcripts.get(vid)
        if not t_data:
            print(f"[content_gen] {i}/{total} {vid} — skipped (no transcript)")
            continue
        print(f"[content_gen] {i}/{total} {vid}")
        results[vid] = generate_metadata(
            video_id=vid,
            transcript_text=t_data["text"],
            existing_title=video.get("title", ""),
            transcript_urls=t_data.get("urls", []),
            force=force,
        )
    return results
