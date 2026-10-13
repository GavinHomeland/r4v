"""Weekly personality refresh for JT Tracy — mines NEW transcripts for fresh catchphrases/quotes.

Only transcripts not mined before are used (tracked in data/personality_refresh_mined.json);
the run is skipped until at least MIN_NEW_TRANSCRIPTS have piled up.

Run manually:   python refresh_personalities.py
Called by:      run_check.ps1 on Sundays (or when a week has been missed)
"""
import json
import random
import subprocess
import sys
import re
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import GEMINI_API_KEY, GEMINI_MODEL, VIDEOS_JSON
from r4v.storage import load_json, save_json

PERSONALITIES_PATH = PROJECT_ROOT / "config" / "personalities.json"
TRANSCRIPTS_DIR    = PROJECT_ROOT / "data" / "transcripts"
FLAG_PATH          = PROJECT_ROOT / "data" / "personality_refresh_flag.json"
MINED_PATH         = PROJECT_ROOT / "data" / "personality_refresh_mined.json"

SAMPLE_SIZE = 40
MIN_NEW_ITEMS = 3
MIN_NEW_TRANSCRIPTS = 5        # don't run until this many un-mined transcripts exist — with only
                               # 1-2 to read, Gemini scrapes filler ("I just work here.")
RECURRING_MIN_TRANSCRIPTS = 2  # catchphrases + closers must appear in this many new transcripts
QUOTE_MIN_WORDS = 8            # quotes must be a complete thought, not a fragment

# Max list sizes. New items go on the front; anything past the cap falls off the back (oldest).
LIST_CAPS = {
    "catchphrases":                 35,
    "real_quotes_from_transcripts": 80,
    "closer_variants":              25,
}

# River-trip chapter start (upload_date, YYYYMMDD). Most videos.json entries have no
# upload_date, so freshness is tracked by MINED_PATH instead; this only guards against a
# late-fetched bike-era transcript whose upload_date IS known.
RIVER_TRIP_START_DATE = "20260718"


def _gemini_client():
    from google import genai
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set in .env")
    return genai.Client(api_key=GEMINI_API_KEY)


def _load_mined_ids() -> set[str] | None:
    """Return the set of already-mined video IDs, or None if tracking hasn't started yet."""
    data = load_json(MINED_PATH)
    if data is None:
        return None
    return set(data.get("mined_ids", []))


def _save_mined_ids(ids: set[str]):
    save_json(MINED_PATH, {"mined_ids": sorted(ids)})


def _transcript_ids() -> set[str]:
    return {p.stem for p in TRANSCRIPTS_DIR.glob("*.json")}


def _load_new_transcripts(mined: set[str]) -> dict[str, str]:
    """Return {video_id: text} for transcripts not mined yet (skipping known pre-river-trip uploads)."""
    pre_chapter = {
        v["id"] for v in (load_json(VIDEOS_JSON) or [])
        if v.get("upload_date") and v["upload_date"] < RIVER_TRIP_START_DATE
    }
    texts = {}
    for p in TRANSCRIPTS_DIR.glob("*.json"):
        if p.stem in mined or p.stem in pre_chapter:
            continue
        try:
            data = load_json(p)
            text = (data or {}).get("text", "").strip()
            if text:
                texts[p.stem] = text
        except Exception:
            pass
    return texts


def _sample_transcripts(all_texts: list[str], n: int) -> list[str]:
    """Return up to n texts sampled from all_texts, capped for prompt size."""
    sample = random.sample(all_texts, min(n, len(all_texts)))
    return [t[:4000] for t in sample]


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — so caption punctuation doesn't break matching."""
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split())


def _count_occurrences(phrase: str, norm_texts: list[str]) -> int:
    """Count how many (normalized) transcripts contain this phrase."""
    needle = _normalize(phrase)
    return sum(1 for t in norm_texts if needle in t) if needle else 0


def _verify(candidates: list[str], norm_texts: list[str], min_transcripts: int,
            min_words: int = 0) -> tuple[list[str], list[tuple[str, str]]]:
    """Split candidates into (kept, dropped-with-reason)."""
    kept, dropped = [], []
    for phrase in candidates:
        if len(phrase.split()) < min_words:
            dropped.append((phrase, f"under {min_words} words"))
            continue
        count = _count_occurrences(phrase, norm_texts)
        if count < min_transcripts:
            dropped.append((phrase, f"in {count}/{len(norm_texts)} transcripts, need {min_transcripts}"))
            continue
        kept.append(phrase)
    return kept, dropped


def _build_prompt(personalities: dict, transcripts: list[str]) -> str:
    jt = personalities.get("jt", {})
    current_catchphrases = json.dumps(jt.get("catchphrases", []), indent=2)
    current_quotes       = json.dumps(jt.get("real_quotes_from_transcripts", []), indent=2)
    current_closers      = json.dumps(jt.get("closer_variants", []), indent=2)
    transcript_block     = "\n\n---\n\n".join(transcripts)

    return f"""You are updating the catchphrases and real quotes for JT Tracy in the Roll4Veterans personality config.

CURRENT catchphrases (do NOT repeat these):
{current_catchphrases}

CURRENT real_quotes_from_transcripts (do NOT repeat these):
{current_quotes}

CURRENT closer_variants (do NOT repeat these):
{current_closers}

TRANSCRIPTS TO MINE ({len(transcripts)} samples):
{transcript_block}

YOUR TASK:
1. Find 4-6 NEW catchphrases JT says repeatedly or that reveal his recurring personality — NOT one-off scene descriptions. "Nature, awe, and wonder." qualifies. "It's like a placid river with raindrops falling in it." does not — that describes one moment, not his voice.
2. Find 4-6 NEW real quotes — verbatim lines that reveal character (humor, warmth, self-deprecation, genuine surprise) in a way that would make sense across multiple videos, not tied to a single scene.
3. Find 1-2 NEW closer_variants ONLY if JT actually signs off videos with a line he repeats. A closer is how he ends a video ("Roll for veterans.", "Take care, everybody.") — not a random last sentence.

RULES:
- Quotes must be complete thoughts of at least {QUOTE_MIN_WORDS} words. No fragments, no small talk ("I just work here."), nothing that reads like a captioning error.
- Catchphrases and closers must show up in at least {RECURRING_MIN_TRANSCRIPTS} of the transcripts — one-offs are dropped automatically.
- Only include items that appear verbatim or near-verbatim in the transcripts above.
- Prefer recurring patterns and personality-revealing moments over vivid-but-unique scene descriptions.
- Never invent or paraphrase.
- Return ONLY valid JSON — no markdown fences, no explanation.

Return this exact JSON structure:
{{
  "add_catchphrases": ["...", "..."],
  "add_quotes": ["...", "..."],
  "add_closers": [],
  "notes": "one sentence summary of what was added and why"
}}

If you cannot find {MIN_NEW_ITEMS} genuinely new items, return empty add lists rather than inventing content.
"""


def _apply_changes(personalities: dict, changes: dict) -> tuple[dict, int]:
    """Prepend new items to the jt section (freshest first), then trim each list to LIST_CAPS.

    New material goes at the front of each list so it surfaces immediately in
    weighted/positional consumers (e.g. closer_variants' week-index rotation), and
    the cap drops the oldest items off the back so the lists never grow unbounded.
    Returns (updated_personalities, n_added).
    """
    jt = personalities["jt"]
    n = 0

    for key, add_key in [
        ("catchphrases",                "add_catchphrases"),
        ("real_quotes_from_transcripts", "add_quotes"),
        ("closer_variants",             "add_closers"),
    ]:
        current = jt.get(key, [])
        to_add = [x for x in changes.get(add_key, []) if x and x not in current]
        n += len(to_add)
        merged = to_add + current
        cap = LIST_CAPS[key]
        if len(merged) > cap:
            print(f"[refresh] {key}: trimming {len(merged) - cap} oldest item(s) to stay at {cap}:")
            for old in merged[cap:]:
                print(f"         - {old!r}")
        jt[key] = merged[:cap]

    return personalities, n


def run(force: bool = False) -> bool:
    """Run the refresh. Returns True if personalities.json was updated."""
    mined = _load_mined_ids()
    if mined is None:
        # First run under mined-ID tracking: everything on disk has already been mined
        # (or is bike-era), so baseline it and start counting from the next new transcript.
        ids = _transcript_ids()
        _save_mined_ids(ids)
        print(f"[refresh] Started tracking — marked {len(ids)} existing transcripts as mined.")
        _write_flag("tracking_started")
        return False

    new = _load_new_transcripts(mined)
    if not new or (len(new) < MIN_NEW_TRANSCRIPTS and not force):
        print(f"[refresh] Only {len(new)} new transcript(s) since last mining "
              f"(need {MIN_NEW_TRANSCRIPTS}) — waiting for more.")
        _write_flag("too_few_new_transcripts", f"{len(new)} new")
        return False

    all_texts = list(new.values())
    norm_texts = [_normalize(t) for t in all_texts]
    transcripts = _sample_transcripts(all_texts, SAMPLE_SIZE)
    print(f"[refresh] {len(all_texts)} new transcripts; sampled {len(transcripts)} for Gemini.")

    personalities = load_json(PERSONALITIES_PATH)
    if not personalities or "jt" not in personalities:
        print("[refresh] personalities.json missing or malformed — aborting.")
        _write_flag("malformed_personalities")
        return False

    prompt = _build_prompt(personalities, transcripts)

    try:
        from google.genai import types as _types
        client = _gemini_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=_types.GenerateContentConfig(temperature=0.7),
        )
        raw = response.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        print(f"[refresh] Gemini call failed: {detail}")
        _write_flag("api_error", detail)
        return False

    try:
        changes = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[refresh] Gemini returned invalid JSON: {e}\n{raw[:300]}")
        _write_flag("json_error")
        return False

    # These transcripts have now been read — don't re-mine them next week.
    _save_mined_ids(mined | set(new))

    # Catchphrases + closers must recur across transcripts; quotes may be one-offs but must
    # really be in a transcript and be a full thought.
    for add_key, min_transcripts, min_words in [
        ("add_catchphrases", RECURRING_MIN_TRANSCRIPTS, 0),
        ("add_closers",      RECURRING_MIN_TRANSCRIPTS, 0),
        ("add_quotes",       1,                         QUOTE_MIN_WORDS),
    ]:
        kept, dropped = _verify(changes.get(add_key, []), norm_texts, min_transcripts, min_words)
        changes[add_key] = kept
        if dropped:
            print(f"[refresh] {add_key} dropped:")
            for phrase, reason in dropped:
                print(f"         [{reason}] {phrase!r}")

    total_proposed = (len(changes.get("add_catchphrases", [])) +
                       len(changes.get("add_quotes", [])) +
                       len(changes.get("add_closers", [])))

    print(f"[refresh] Items proposed by Gemini: +{total_proposed}")
    print(f"[refresh] Notes: {changes.get('notes','')}")

    # Apply (dedups against existing items) BEFORE deciding whether there's anything
    # worth saving — total_proposed can clear MIN_NEW_ITEMS even when every proposed
    # item already exists verbatim (e.g. Gemini re-surfacing an existing line from a
    # random transcript sample), which would otherwise save + flag "updated" with zero
    # real change.
    updated, n_changes = _apply_changes(personalities, changes)
    print(f"[refresh] Items actually new after de-dup: +{n_changes}")

    if n_changes < MIN_NEW_ITEMS and not force:
        print(f"[refresh] Fewer than {MIN_NEW_ITEMS} genuinely new item(s) — skipping personalities update.")
        _write_flag("insufficient_new_items")
        return False

    save_json(PERSONALITIES_PATH, updated)
    print(f"[refresh] personalities.json updated ({n_changes} change(s)).")

    _write_flag("updated")
    return True


def _write_flag(status: str, detail: str = ""):
    record = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }
    if detail:
        record["detail"] = detail[:500]
    save_json(FLAG_PATH, record)
    print(f"[refresh] Flag written: {status}" + (f" — {detail[:200]}" if detail else ""))


def _git_commit_and_push(updated: bool):
    """Commit flag (and personalities if updated) and push."""
    files = [str(FLAG_PATH)]
    if updated:
        files.append(str(PERSONALITIES_PATH))

    try:
        subprocess.run(["git", "add"] + files, cwd=PROJECT_ROOT, check=True)
        msg = ("Personalities: weekly JT catchphrase/quote refresh"
               if updated else "Personalities: weekly refresh check (no changes)")
        result = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=PROJECT_ROOT, capture_output=True, text=True
        )
        if result.returncode != 0:
            if "nothing to commit" in result.stdout + result.stderr:
                print("[refresh] Nothing new to commit.")
                return
            print(f"[refresh] git commit failed: {result.stderr}")
            return

        push = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=PROJECT_ROOT, capture_output=True, text=True
        )
        if push.returncode == 0:
            print("[refresh] Pushed to origin/main.")
        else:
            print(f"[refresh] git push failed (local commit kept): {push.stderr[:200]}")
    except Exception as e:
        print(f"[refresh] git error: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Update even if fewer than 3 new items found")
    parser.add_argument("--no-push", action="store_true",
                        help="Skip git commit/push")
    args = parser.parse_args()

    try:
        updated = run(force=args.force)
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        print(f"[refresh] Unexpected failure: {detail}")
        _write_flag("crash", detail)
        raise
    if not args.no_push:
        _git_commit_and_push(updated)
