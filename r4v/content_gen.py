"""AI-powered metadata generation using Google Gemini API (free tier)."""
import json
import random
import re
import urllib.request
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
        "COMMENT STYLE (for YouTube comments — NOT descriptions):",
        "  - No greeting, no opener — just launch straight into the reaction or reply",
        "  - NEVER open with 'Hello friend!' — that opener is for video descriptions only",
        "  - If someone in the thread asked a question, answer it directly",
        "  - NEVER reply to a comment posted by the same account",
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

    priorities = gavin.get("editorial_priorities", [])

    lines = [
        "ABOUT GAVIN (JT's brother — writes comment_gavin ONLY, not descriptions):",
        f"  {gavin.get('relationship_to_jt', '')}",
        "",
        "GAVIN'S COMMENT RULES:",
        "  - No greeting, no opener — just launch straight into the reply",
        "  - 1-2 sentences responding directly to JT's specific words in comment_jt — reference them explicitly",
        "  - Warm, slightly goofy tone; may briefly mention the Kansas farm (pigs, brassicas, guinea fowl)",
        "  - Every 3rd or 4th comment: append a non-sequitur 'Real Life Hack' using one lead-in + one hack",
        "  - If JT's comment contains a question, answer it",
        "  - NEVER reply to a comment posted by the same account",
        "",
        "GAVIN'S EDITORIAL PRIORITIES:",
    ]
    for p in priorities:
        lines.append(f"  - {p}")
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


def _load_known_family() -> str:
    """Load known family members so Gemini can address them by name."""
    try:
        data = json.loads(_PERSONALITIES_PATH.read_text(encoding="utf-8"))
        family = data.get("known_family", {})
    except Exception:
        return ""
    if not family:
        return ""
    lines = ["KNOWN FAMILY IN THE COMMENTS (address by name, not generically):"]
    for handle, info in family.items():
        lines.append(f"  @{handle} — {info.get('name', handle)}: {info.get('relationship', '')}")
    return "\n".join(lines)


def _build_system_prompt() -> str:
    jt_profile = _load_jt_profile()
    gavin_profile = _load_gavin_profile()
    family_note = _load_known_family()
    return (
        "You are the content engine for the Roll4Veterans (@roll4veterans) YouTube channel.\n\n"
        "=== JT TRACY — channel owner, use for title/description/comment_jt ===\n"
        "{jt_profile}\n\n"
        "=== GAVIN HOMELAND — channel manager, use ONLY for comment_gavin ===\n"
        "{gavin_profile}\n\n"
        "{family_note}\n\n"
        "Team RWB (teamrwb.org) connects veterans through physical and social activity. "
        "R4V social: @roll4veterans on FB/IG/TT/YT. Website: r4v.songseekers.org"
    ).format(
        jt_profile=jt_profile or "JT Tracy — veteran cyclist, R4V founder.",
        gavin_profile=gavin_profile or "Gavin — channel manager, warm and goofy.",
        family_note=family_note,
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


def _pick_gavin_hack() -> str:
    """Pre-select a random lead_in + hack pair 25% of the time; else return ''."""
    if random.random() > 0.25:
        return ""
    try:
        data = json.loads(_PERSONALITIES_PATH.read_text(encoding="utf-8"))
        gavin = data.get("gavin", {})
        lead_ins = gavin.get("conversational_lead_ins", [])
        hacks = gavin.get("life_hack_pool", [])
        if lead_ins and hacks:
            return f"{random.choice(lead_ins)} {random.choice(hacks)}"
    except Exception:
        pass
    return ""


def _extract_transcript_opening(transcript_text: str) -> str:
    """Return the first meaningful sentence from the transcript (JT's actual words).

    Strips speaker-change markers (>>) and disfluencies, then takes up to the
    first sentence-ending punctuation or ~120 chars — whichever comes first.
    Returns empty string if the transcript is blank or too short to be useful.
    """
    import re as _re
    text = (transcript_text or "").strip()
    if not text:
        return ""
    # Remove speaker-change lines (lines that start with >>)
    lines = [l for l in text.splitlines() if not l.strip().startswith(">>")]
    text = " ".join(lines).strip()
    # Collapse whitespace
    text = _re.sub(r"\s+", " ", text)
    # Find first sentence boundary
    m = _re.search(r"[.!?]", text[:200])
    sentence = text[:m.start() + 1] if m else text[:120]
    # Strip trailing filler that makes bad openers ("So, " / "Uh, " at the very start)
    sentence = _re.sub(r"^(So[,.]?\s+|Uh[,.]?\s+|Um[,.]?\s+|And\s+|Well[,.]?\s+)", "", sentence, flags=_re.I)
    return sentence.strip()


def _fetch_weather(location: str) -> str:
    """Fetch a one-line weather summary from wttr.in. Returns '' on any failure."""
    if not location:
        return ""
    try:
        q = quote_plus(location)
        url = f"https://wttr.in/{q}?format=3"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            return resp.read().decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _guess_jt_location(existing_title: str, existing_description: str, transcript_text: str) -> str:
    """Extract a best-guess location for JT from available text."""
    # Prefer title — usually has the location
    for text in (existing_title, existing_description, transcript_text[:800]):
        # "in [City, State]" pattern
        m = re.search(
            r'\bin\s+([A-Z][a-zA-Z]+(?:[\s-][A-Z][a-zA-Z]+)?'
            r'(?:,\s*(?:FL|GA|AL|MS|LA|TX|NM|AZ|CA|NV))?)',
            text,
        )
        if m:
            return m.group(1).strip()
    # Fall back to last capitalized sequence in title
    caps = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', existing_title)
    return caps[-1] if caps else ""


def _build_local_color_hint(
    existing_title: str = "",
    existing_description: str = "",
    transcript_text: str = "",
) -> str:
    """Fetch weather for JT's location and Gavin's Kansas. Return an injection hint or ''."""
    jt_loc = _guess_jt_location(existing_title, existing_description, transcript_text)
    jt_weather = _fetch_weather(jt_loc) if jt_loc else ""
    gavin_weather = _fetch_weather("Salina, Kansas")

    lines = []
    if jt_weather:
        lines.append(f"  JT's location right now — {jt_weather}")
    if gavin_weather:
        lines.append(f"  Gavin's Kansas right now — {gavin_weather}")
    if not lines:
        return ""
    hint = "\n".join(lines)
    return (
        "LOCAL COLOR HINTS (weave in naturally if it fits — do NOT force it):\n"
        f"{hint}\n"
        "  (e.g. Gavin might mention it's cold in Kansas, or JT might note the weather as he rides)\n\n"
    )


def _format_ai_notes(ai_notes: str) -> str:
    text = (ai_notes or "").strip()
    if not text:
        return ""
    lines = "\n".join(f">> {line.lstrip('> ').strip()}" for line in text.splitlines() if line.strip())
    return f"CORRECTIONS / NOTES FROM EDITOR (follow these exactly):\n{lines}\n\n"


def build_prompt(
    transcript_text: str,
    existing_title: str = "",
    existing_description: str = "",
    jt_opener: str = "",
    ai_notes: str = "",
    gavin_hack: str = "",
    local_color: str = "",
) -> str:
    """Build the user prompt string without calling the API. Used by the GUI prompt editor."""
    opening = _extract_transcript_opening(transcript_text)
    opening_hint = (
        f'TRANSCRIPT OPENING (use this or a light prose adaptation as your first sentence '
        f'after "Hello friend!"): "{opening}"\n'
    ) if opening else ""
    if gavin_hack:
        hack_hint = (
            f'After his 1-2 sentences, append this closing line VERBATIM — '
            f'copy it character for character, no labels, no headers, no changes: '
            f'"{gavin_hack}"\n'
        )
    else:
        hack_hint = "End after his 1-2 sentences. Do not add anything extra.\n"
    return USER_PROMPT_TMPL.format(
        existing_title=existing_title or "(none)",
        existing_description=existing_description or "(none — JT hasn't written one yet)",
        transcript_text=transcript_text,
        ai_notes_block=_format_ai_notes(ai_notes),
        transcript_opening_hint=opening_hint,
        gavin_hack_hint=hack_hint,
        local_color_hint=local_color,
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
that voice. If it contains lines starting with "[[" — treat those as explicit editor instructions
you MUST follow for this video (e.g. a name spelling, a detail to include, a correction).
A description can contain both: prose sections to model and "[[" lines to execute.

{local_color_hint}{ai_notes_block}FULL TRANSCRIPT:
{transcript_text}

---

Now write the description. The ONLY fixed rules are:

FIXED (non-negotiable):
- First line: Hello friend! + one relevant emoji. That line alone. Then \\n\\n.
- No headers, no bullet lists, no hashtags anywhere in the body.
- Names and real details from the transcript — if someone is named, use it.
- If a URL appears in the transcript or existing description, include it naturally.
- 1-2 emojis in the body where they fit. Not forced.
- End with \\n\\n then a SIGNATURE CLOSER on its own line — pick whichever fits the mood.

{transcript_opening_hint}FEEL (not a formula — let the transcript dictate the shape):
Write like JT talking to a friend who wasn't there. Structure comes from what actually \
happened, not from a template. Some videos are one strong moment; write that. Some are \
a string of encounters; follow the thread. Zoom out to the mission when it fits naturally; \
stay close to the moment when it doesn't.

comment_jt is WRITTEN BY JT (@roll4veterans). JT was there — he's commenting on his own video.
No greeting, no opener — jump straight into a specific reaction to what happened. \
Drop one relevant emoji naturally in the text (not at the start). 1-2 sentences max. \
End with a question for viewers or an invitation to share. \
JT speaks from experience — he does NOT ask himself what something was like. MUST NOT be empty.

comment_gavin is WRITTEN BY GAVIN from his @erictracy5584 account. Gavin is JT's actual brother, watching from his farm in Kansas and replying to comment_jt. No greeting — just dive straight into 1-2 sentences reacting to JT's specific words. Warm, slightly goofy. If JT's comment contains a question, answer it. {gavin_hack_hint}NEVER reply to a comment by the same account. MUST NOT be empty.

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
        lines.append(f"{label} \u2192 {url}")
    return "\n".join(lines)


def generate_metadata(
    video_id: str,
    transcript_text: str,
    existing_title: str = "",
    existing_description: str = "",
    transcript_urls: list[str] | None = None,
    force: bool = False,
    prompt_override: str | None = None,
    ai_notes: str = "",
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
    gavin_hack = _pick_gavin_hack()
    local_color = _build_local_color_hint(
        existing_title=existing_title,
        existing_description=existing_description,
        transcript_text=transcript_text,
    )
    prompt = prompt_override if prompt_override is not None else build_prompt(
        transcript_text=transcript_text,
        existing_title=existing_title,
        existing_description=existing_description,
        ai_notes=ai_notes,
        gavin_hack=gavin_hack,
        local_color=local_color,
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
