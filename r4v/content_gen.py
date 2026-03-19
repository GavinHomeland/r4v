"""AI-powered metadata generation using Google Gemini API (free tier)."""
import json
import random
import re
from pathlib import Path
from urllib.parse import quote_plus
from google import genai
from google.genai import types

from config.settings import GEMINI_API_KEY, GEMINI_MODEL, GENERATED_DIR, FOOTER_TEMPLATE
from r4v.storage import load_json, save_json

_client: genai.Client | None = None

_PERSONALITIES_PATH = Path(__file__).parent.parent / "config" / "personalities.json"


def _load_jt_profile() -> str:
    """Load JT's personality profile from config/personalities.json."""
    try:
        data = json.loads(_PERSONALITIES_PATH.read_text(encoding="utf-8"))
        jt = data.get("jt", {})
    except Exception:
        return ""

    comment_opener = jt.get("comment_opener", "Hey, brother —")
    comment_variants = jt.get("comment_opener_variants", [comment_opener])

    lines = [
        f"ABOUT JT: {jt.get('background', '')}",
        "",
        f"DESCRIPTION OPENER (mandatory, first line of every description): {jt.get('signature_opener', 'Hello friend!')}",
        f"SIGNATURE CLOSER (pick one that fits the mood — vary it): "
        + ", ".join(
            f'"{v}"' for v in (
                [jt.get("signature_closer", "Roll for veterans.")] +
                jt.get("closer_variants", [])
            )
        ),
        "",
        f"COMMENT OPENER (for YouTube comments — brotherly, personal, NOT 'Hello friend!'):",
        f"  Default: {comment_opener}",
        "  Variants (pick based on the video's mood):",
    ]
    for v in comment_variants:
        lines.append(f"    - \"{v}\"")
    lines += [
        "  NEVER open a comment with 'Hello friend!' — that opener is for video descriptions only.",
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


def _load_gavin_profile() -> str:
    """Load Gavin's personality profile from config/personalities.json."""
    try:
        data = json.loads(_PERSONALITIES_PATH.read_text(encoding="utf-8"))
        gavin = data.get("gavin", {})
    except Exception:
        return ""

    lead_ins = gavin.get("conversational_lead_ins", [])
    hacks = gavin.get("life_hack_pool", [])
    priorities = gavin.get("editorial_priorities", [])

    opener = gavin.get("comment_opener", "Hi, Brother")
    opener_variants = gavin.get("comment_opener_variants", [opener])
    lines = [
        "ABOUT GAVIN (JT's brother — writes comment_gavin ONLY, not descriptions):",
        f"  {gavin.get('relationship_to_jt', '')}",
        "",
        "GAVIN'S COMMENT RULES:",
        f"  - Gavin is JT's actual brother. He always opens with '{opener}' + relevant emoji as the ENTIRE first line",
        "  - Then a blank line (\\n\\n), then 1-2 sentences",
        "  - Responds DIRECTLY to JT's specific words in comment_jt — reference them explicitly",
        "  - Warm, slightly goofy tone; may briefly mention the Kansas farm (pigs, brassicas, guinea fowl)",
        "  - Every 3rd or 4th comment: append a non-sequitur 'Real Life Hack' using one lead-in + one hack",
        f"  - Opener variants (pick one): {', '.join(repr(v) for v in opener_variants)}",
        f"  - Format: \"{opener} 🐷\\n\\n[1-2 sentences responding to JT's comment]\"",
        "",
        "GAVIN'S EDITORIAL PRIORITIES:",
    ]
    for p in priorities:
        lines.append(f"  - {p}")
    lines += [
        "",
        "LEAD-INS FOR LIFE HACKS (pick one randomly when adding a hack):",
    ]
    for li in lead_ins[:6]:
        lines.append(f"  \"{li}\"")
    lines += [
        "",
        "LIFE HACK POOL (sample — choose one that doesn't obviously relate to the video topic):",
    ]
    for h in hacks[:8]:
        lines.append(f"  \"{h}\"")

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
    jt_profile = _load_jt_profile()
    gavin_profile = _load_gavin_profile()
    return (
        "You are the content engine for the Roll4Veterans (@roll4veterans) YouTube channel.\n\n"
        "=== JT TRACY — channel owner, use for title/description/comment_jt ===\n"
        "{jt_profile}\n\n"
        "=== GAVIN HOMELAND — channel manager, use ONLY for comment_gavin ===\n"
        "{gavin_profile}\n\n"
        "Team RWB (teamrwb.org) connects veterans through physical and social activity. "
        "R4V social: @roll4veterans on FB/IG/TT/YT. Website: r4v.songseekers.org"
    ).format(
        jt_profile=jt_profile or "JT Tracy — veteran cyclist, R4V founder.",
        gavin_profile=gavin_profile or "Gavin — channel manager, warm and goofy.",
    )


def _pick_jt_opener() -> str:
    """Pick a random JT comment opener from personalities.json."""
    try:
        data = json.loads(_PERSONALITIES_PATH.read_text(encoding="utf-8"))
        variants = data.get("jt", {}).get("comment_opener_variants", [])
        if variants:
            return random.choice(variants)
    except Exception:
        pass
    return "Man, I tell you what —"


def build_prompt(
    transcript_text: str,
    existing_title: str = "",
    existing_description: str = "",
    jt_opener: str = "",
) -> str:
    """Build the user prompt string without calling the API. Used by the GUI prompt editor."""
    return USER_PROMPT_TMPL.format(
        existing_title=existing_title or "(none)",
        existing_description=existing_description or "(none — JT hasn't written one yet)",
        transcript_text=transcript_text,
        jt_opener=jt_opener or _pick_jt_opener(),
    )


USER_PROMPT_TMPL = """\
Read this full transcript carefully. Pull out the most interesting, specific, \
and human moments — names of people JT met (with any title or role mentioned), \
places, distances, struggles, unexpected things, things that made him laugh or \
feel something. If a URL is mentioned, note it.

EXISTING TITLE: {existing_title}

EXISTING DESCRIPTION:
{existing_description}

Read the existing description above carefully. If it reads as natural, flowing prose or narrative —
JT talking to fans, telling a story — treat it as the tone benchmark: study how he writes and match
that voice. If it contains lines starting with ">>" or disjointed fragments (a name spelling, a
specific detail to weave in, a person or place to mention) — treat those as explicit instructions
you MUST follow for this video. A description can contain both: prose sections to model and ">>"
lines to execute.

FULL TRANSCRIPT:
{transcript_text}

---

Now write the description. Guidelines:

- MUST open with: Hello friend! [relevant emoji]  — this greeting is the ENTIRE first line.
  Then a blank line (\\n\\n), then the rest of the description.
  Format: "Hello friend! 🚴\\n\\nJT is riding through..."
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
- End with a blank line (\\n\\n) then one of JT's SIGNATURE CLOSER variants on its own line \
(e.g. "Roll for veterans." or "Sunshine and happiness." — pick the one that fits the mood). \
The closer must be separated from the last paragraph by \\n\\n, never inline with it.

comment_jt is WRITTEN BY JT from his @roll4veterans account. JT was there in the video. He is now commenting on his own video to connect with his audience/fans about what he experienced. MUST open with exactly "{jt_opener}" + a relevant emoji on the first line — do not substitute a different opener. Then blank line (\n\n), then 1-2 sentences inviting fans to engage with what JT saw or felt. He speaks from his own experience — he does NOT ask himself what something was like. Ask the audience a question, or invite them to share a related story. MUST NOT be empty.
Format: "{jt_opener} 🌊\n\nDan's 37 years blew me away. Any of you have a story like that from your local Legion post?"

comment_gavin is WRITTEN BY GAVIN from his @erictracy5584 account. Gavin is JT's actual brother, watching from his farm in Kansas and replying to comment_jt. Open with "Hi, Brother"/"Hi, Bro"/"Hey, Bro" + emoji on first line, blank line (\n\n), then 1-2 sentences reacting to JT's specific words. Warm, slightly goofy. Occasionally append a non-sequitur life hack. MUST NOT be empty.
Format: "Hi, Brother 🌽\n\n[Gavin's reaction to what JT said in comment_jt]"

For locations: list every specific named place from the transcript (towns, businesses, parks, landmarks). Any place named in the transcript or description MUST appear in this list — do not omit it. Be granular: "Pelican Cove, Destin, FL" beats "Destin, FL". Use JT's route (Key West → Gulf Coast west → Los Angeles → Flagstaff) to disambiguate. If no specific places are named, return [].

Generate the following and respond ONLY with valid JSON (no markdown, no extra text):
{{
  "title": "Punchy YouTube Short title, max 60 chars, action-oriented, no generic phrases",
  "description": "Full description. First line: Hello friend! + emoji. Then \n\n. Then 3-4 natural paragraphs. No headers, no lists. End with \n\n then a closing line (e.g. Roll for veterans.) on its own.",
  "tags": ["15-20 YouTube tags", "mix of broad cycling/veteran tags and specific content tags"],
  "hashtags": "space-separated hashtags — always_include first, then 5-7 from evergreen pool, then content-specific. Aim for 12-16 total.",
  "comment_jt": "WRITTEN BY JT — JT was there, speaks from experience, invites audience to engage. Opener variant + emoji, blank line, 1-2 sentences. MUST NOT be empty.",
  "comment_gavin": "WRITTEN BY GAVIN (JT's brother in Kansas) — Hi Brother/Hi Bro + emoji, blank line, 1-2 sentences reacting to comment_jt. MUST NOT be empty.",
  "locations": [
    {{"label": "Place name, City, State", "query": "plain text Google Maps search"}}
  ]
}}"""


def _build_footer(hashtags: str, urls: list[str]) -> str:
    extra = ""
    if urls:
        extra = "\n" + "\n".join(f"\U0001f517 {u}" for u in urls)
    return FOOTER_TEMPLATE.format(extra_links=extra, hashtags=hashtags)


def _build_location_comment(locations: list[dict]) -> str:
    """Convert a list of {label, query} dicts to a formatted comment string.

    Format per line:  https://maps.google.com/?q=... \u2190 Label
    Returns empty string if no locations.
    """
    if not locations:
        return ""
    lines = []
    for loc in locations:
        label = loc.get("label", "").strip()
        query = loc.get("query", label).strip()
        if not query:
            continue
        url = f"https://maps.google.com/?q={quote_plus(query)}"
        lines.append(f"{url} \u2190 {label}")
    return "\n".join(lines)


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

    # Preserve approval so regeneration never resets it
    existing_approved = None
    if cache_path.exists():
        try:
            old = load_json(cache_path)
            if old:
                existing_approved = old.get("approved")
        except Exception:
            pass

    client = _get_client()
    prompt = prompt_override if prompt_override is not None else build_prompt(
        transcript_text=transcript_text,
        existing_title=existing_title,
        existing_description=existing_description,
        jt_opener=_pick_jt_opener(),
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

    comment_jt = generated.get("comment_jt") or generated.get("comment", "")
    comment_gavin = generated.get("comment_gavin", "")
    locations = generated.get("locations", [])
    if isinstance(locations, list):
        locations = [loc for loc in locations if isinstance(loc, dict)]
    else:
        locations = []
    comment_location = _build_location_comment(locations)

    result = {
        "video_id": video_id,
        "existing_title": existing_title,
        "title": generated.get("title", existing_title),
        "description": full_description,
        "description_base": base_desc,
        "tags": generated.get("tags", []),
        "hashtags": hashtags,
        # comment = JT's comment (backward compat alias)
        "comment": comment_jt,
        "comment_jt": comment_jt,
        "comment_gavin": comment_gavin,
        "comment_location": comment_location,
        "approved": existing_approved,
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
        description = video.get("description", "").strip()
        title_short = video.get("title", "")[:50]
        if not t_data:
            # Fallback: use existing description as source (e.g. private/unlisted videos
            # with no captions but a detailed description already on YouTube)
            if description and len(description) > 100:
                print(f"[content_gen] {i}/{total} {vid}  \"{title_short}\" — using description (no transcript)")
                t_data = {"text": description, "urls": []}
            else:
                print(f"[content_gen] {i}/{total} {vid}  \"{title_short}\" — skipped (no transcript or description)")
                continue
        else:
            print(f"[content_gen] {i}/{total} {vid}  \"{title_short}\"")
        results[vid] = generate_metadata(
            video_id=vid,
            transcript_text=t_data["text"],
            existing_title=video.get("title", ""),
            existing_description=video.get("description", ""),
            transcript_urls=t_data.get("urls", []),
            force=force,
        )
    return results
