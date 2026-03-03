"""AI-powered metadata generation using Google Gemini API (free tier)."""
import json
import re
from pathlib import Path
from google import genai
from google.genai import types

from config.settings import GEMINI_API_KEY, GEMINI_MODEL, GENERATED_DIR, FOOTER_TEMPLATE
from r4v.storage import load_json, save_json

_client: genai.Client | None = None

_PERSONALITIES_PATH = Path(__file__).parent.parent / "config" / "personalities.json"


def _load_jt_profile() -> str:
    """Load JT's personality profile from config/personalities.json and format it for the prompt."""
    try:
        data = json.loads(_PERSONALITIES_PATH.read_text(encoding="utf-8"))
        jt = data.get("jt", {})
    except Exception:
        return ""

    lines = [
        f"ABOUT JT: {jt.get('background', '')}",
        "",
        f"SIGNATURE OPENER (mandatory, every post): {jt.get('signature_opener', 'Hello friend!')}",
        f"SIGNATURE CLOSER: {jt.get('signature_closer', 'Roll for veterans.')}",
        "",
        "HIS CATCHPHRASES (use naturally when relevant):",
    ]
    for phrase in jt.get("catchphrases", []):
        lines.append(f"  - \"{phrase}\"")

    lines += ["", "HOW HE TALKS:"]
    for trait in jt.get("voice_traits", []):
        lines.append(f"  - {trait}")

    lines += ["", "WHAT HE ALWAYS NOTICES AND MENTIONS:"]
    for thing in jt.get("what_he_notices", []):
        lines.append(f"  - {thing}")

    lines += ["", "REAL LINES FROM HIS VIDEOS (study this voice — match it):"]
    for quote in jt.get("real_quotes_from_transcripts", []):
        lines.append(f"  \"{quote}\"")

    lines += ["", "NEVER DO THIS IN DESCRIPTIONS:"]
    for avoid in jt.get("avoid_in_descriptions", []):
        lines.append(f"  - {avoid}")

    ht = jt.get("hashtag_guidance", {})
    if ht:
        always = ht.get("always_include", [])
        pool = ht.get("evergreen_pool", [])
        rules = ht.get("content_specific_rules", [])
        lines += [
            "",
            "HASHTAG RULES — follow these exactly:",
            f"  Always include: {' '.join(always)}",
            f"  Evergreen pool (pick 5-7 that fit this video): {' '.join(pool)}",
            "  Content-specific additions:",
        ]
        for rule in rules:
            lines.append(f"    - {rule}")

    return "\n".join(lines)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY is not set in .env\n"
                "Get a free key at https://aistudio.google.com/apikey"
            )
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _build_system_prompt() -> str:
    profile = _load_jt_profile()
    base = (
        "You are writing YouTube descriptions and comments in the exact voice of JT Tracy "
        "for the Roll4Veterans (@roll4veterans) channel.\n\n"
        "{profile}\n\n"
        "Team RWB (teamrwb.org) connects veterans through physical and social activity. "
        "R4V social: @roll4veterans on FB/IG/TT/YT. Website: r4v.songseekers.org"
    )
    return base.format(profile=profile if profile else "JT Tracy — veteran cyclist, R4V founder.")


def build_prompt(
    transcript_text: str,
    existing_title: str = "",
    existing_description: str = "",
) -> str:
    """Build the user prompt string without calling the API. Used by the GUI prompt editor."""
    return USER_PROMPT_TMPL.format(
        existing_title=existing_title or "(none)",
        existing_description=existing_description or "(none — not yet fetched)",
        transcript_text=transcript_text,
    )


USER_PROMPT_TMPL = """\
Read this full transcript carefully. Pull out the most interesting, specific, \
and human moments — names of people JT met (with any title or role mentioned), \
places, distances, struggles, unexpected things, things that made him laugh or \
feel something. If a URL is mentioned, note it.

EXISTING TITLE: {existing_title}

EXISTING DESCRIPTION (study the tone — this is the benchmark for quality and feel):
{existing_description}

FULL TRANSCRIPT:
{transcript_text}

---

Now write the description. Guidelines:

- MUST open with: Hello friend! [relevant emoji]
- Then write naturally, like JT talking to a friend. 3-4 paragraphs, no headers, no bullet lists.
- Each paragraph should flow into the next. Mix the immediate moment (what happened in this video) \
with a little of the bigger picture (the ride, the mission, the people).
- Use specific names, places, numbers, quotes from the transcript. \
If someone is named in the transcript, use their name. If a title is mentioned (pastor, sheriff, \
store owner, veteran, etc.), include it. Real details make it real.
- If a URL was mentioned in the transcript or is in the existing description, weave it in naturally.
- Scatter 1-2 emojis through the body where they feel natural — not forced.
- NO hashtags anywhere in the description body.
- Don't sound like AI. No "In this captivating short..." or "Join JT as he..." — just tell it straight.

For the comment: also starts with "Hello friend!" + emoji, then 1-2 sentences. \
Ask a real question based on something specific in this video, or invite people to share \
something related. Make it feel like the start of a conversation, not a caption.

Generate the following and respond ONLY with valid JSON (no markdown, no extra text):
{{
  "title": "Punchy YouTube Short title, max 60 chars, action-oriented, no generic phrases",
  "description": "The full description. 3-4 natural paragraphs. Starts with Hello friend! + emoji. No headers, no lists.",
  "tags": ["15-20 YouTube tags", "mix of broad cycling/veteran tags and specific content tags"],
  "hashtags": "space-separated hashtags — follow the HASHTAG RULES in your instructions exactly: always_include first, then 5-7 from the evergreen pool that fit, then content-specific additions. Aim for 12-16 total. No hashtags for topics not in the transcript.",
  "comment": "Hello friend! [emoji] 1-2 sentences — specific to this video, invites a real response"
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
    existing_description: str = "",
    transcript_urls: list[str] | None = None,
    force: bool = False,
    prompt_override: str | None = None,
) -> dict:
    """Generate AI metadata for a video. Caches result in data/generated/{video_id}_metadata.json.

    prompt_override: if provided, skip building the prompt from USER_PROMPT_TMPL and use this
    string directly. Used by the GUI prompt editor when the user has edited the prompt.
    """
    cache_path = GENERATED_DIR / f"{video_id}_metadata.json"
    if not force and prompt_override is None and cache_path.exists():
        cached = load_json(cache_path)
        if cached and cached.get("title"):
            return cached

    client = _get_client()
    prompt = prompt_override if prompt_override is not None else build_prompt(
        transcript_text=transcript_text,
        existing_title=existing_title,
        existing_description=existing_description,
    )

    print(f"[content_gen] Generating metadata for {video_id} ...")
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_build_system_prompt(),
            temperature=0.9,
        ),
    )
    raw = response.text.strip()

    # Strip markdown code fences if Gemini wraps output
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        generated = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Gemini returned invalid JSON for {video_id}: {e}\nRaw: {raw}")

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
        "approved": None,
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
            existing_description=video.get("description", ""),
            transcript_urls=t_data.get("urls", []),
            force=force,
        )
    return results
