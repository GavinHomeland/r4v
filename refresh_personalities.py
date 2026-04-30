"""Weekly personality refresh for JT Tracy — mines transcripts for fresh catchphrases/quotes.

Run manually:   python refresh_personalities.py
Called by:      run_check.ps1 on Sundays
"""
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import GEMINI_API_KEY, GEMINI_MODEL
from r4v.storage import load_json, save_json

PERSONALITIES_PATH = PROJECT_ROOT / "config" / "personalities.json"
TRANSCRIPTS_DIR    = PROJECT_ROOT / "data" / "transcripts"
FLAG_PATH          = PROJECT_ROOT / "data" / "personality_refresh_flag.json"

SAMPLE_SIZE = 40
MIN_NEW_ITEMS = 3
SIZE_WARN_THRESHOLD = 50        # total items across catchphrases + quotes + closers
CATCHPHRASE_MIN_TRANSCRIPTS = 2  # catchphrase must appear in this many transcripts to be kept


def _gemini_client():
    from google import genai
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set in .env")
    return genai.Client(api_key=GEMINI_API_KEY)


def _load_all_transcripts() -> list[str]:
    """Return all transcript texts from the full directory (uncapped, for frequency checks)."""
    texts = []
    for p in TRANSCRIPTS_DIR.glob("*.json"):
        try:
            data = load_json(p)
            text = (data or {}).get("text", "").strip()
            if text:
                texts.append(text)
        except Exception:
            pass
    return texts


def _sample_transcripts(all_texts: list[str], n: int) -> list[str]:
    """Return up to n texts sampled from all_texts, capped for prompt size."""
    sample = random.sample(all_texts, min(n, len(all_texts)))
    return [t[:4000] for t in sample]


def _count_occurrences(phrase: str, all_texts: list[str]) -> int:
    """Count how many transcripts contain this phrase (case-insensitive)."""
    needle = phrase.lower().strip()
    return sum(1 for t in all_texts if needle in t.lower())


def _verify_catchphrases(candidates: list[str], all_texts: list[str]) -> tuple[list[str], list[tuple[str, int]]]:
    """Split candidates into (verified, dropped). Dropped = appeared in fewer than threshold transcripts."""
    verified, dropped = [], []
    for phrase in candidates:
        count = _count_occurrences(phrase, all_texts)
        if count >= CATCHPHRASE_MIN_TRANSCRIPTS:
            verified.append(phrase)
        else:
            dropped.append((phrase, count))
    return verified, dropped


def _check_size_warning(personalities: dict):
    """Print a warning if the JT lists are large enough to meaningfully inflate token cost."""
    jt = personalities.get("jt", {})
    total = (len(jt.get("catchphrases", [])) +
             len(jt.get("real_quotes_from_transcripts", [])) +
             len(jt.get("closer_variants", [])))
    if total >= SIZE_WARN_THRESHOLD:
        print(f"[refresh] ⚠ SIZE WARNING: {total} total items in JT lists "
              f"(threshold: {SIZE_WARN_THRESHOLD}). Consider manually pruning "
              f"config/personalities.json to keep Gemini prompt costs down.")
    return total


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
3. Find 1-2 NEW closer_variants if any natural sign-off lines appear.

RULES:
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
    """Append new items to the jt section (additive only). Returns (updated_personalities, n_added)."""
    jt = personalities["jt"]
    n = 0

    for key, add_key in [
        ("catchphrases",                "add_catchphrases"),
        ("real_quotes_from_transcripts", "add_quotes"),
        ("closer_variants",             "add_closers"),
    ]:
        current = jt.get(key, [])
        to_add = [x for x in changes.get(add_key, []) if x and x not in current]
        current.extend(to_add)
        n += len(to_add)
        jt[key] = current

    return personalities, n


def run(force: bool = False) -> bool:
    """Run the refresh. Returns True if personalities.json was updated."""
    print("[refresh] Loading transcripts...")
    all_texts = _load_all_transcripts()
    if not all_texts:
        print("[refresh] No transcripts found — skipping.")
        _write_flag("no_transcripts")
        return False

    transcripts = _sample_transcripts(all_texts, SAMPLE_SIZE)
    print(f"[refresh] {len(all_texts)} total transcripts; sampled {len(transcripts)} for Gemini.")

    personalities = load_json(PERSONALITIES_PATH)
    if not personalities or "jt" not in personalities:
        print("[refresh] personalities.json missing or malformed — aborting.")
        return False

    _check_size_warning(personalities)
    prompt = _build_prompt(personalities, transcripts)

    from google.genai import types as _types
    client = _gemini_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=_types.GenerateContentConfig(temperature=0.7),
    )
    raw = response.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        changes = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[refresh] Gemini returned invalid JSON: {e}\n{raw[:300]}")
        _write_flag("json_error")
        return False

    # Frequency-check catchphrases against the full corpus — scene-specific one-offs get dropped.
    # Quotes and closers pass through: they're allowed to be one-offs if they reveal character.
    raw_catchphrases = changes.get("add_catchphrases", [])
    if raw_catchphrases:
        verified, dropped = _verify_catchphrases(raw_catchphrases, all_texts)
        changes["add_catchphrases"] = verified
        if dropped:
            print(f"[refresh] Catchphrases dropped (too video-specific — found in <{CATCHPHRASE_MIN_TRANSCRIPTS} transcripts):")
            for phrase, count in dropped:
                n_total = len(all_texts)
                print(f"         [{count}/{n_total}] {phrase!r}")

    total_adds = (len(changes.get("add_catchphrases", [])) +
                  len(changes.get("add_quotes", [])) +
                  len(changes.get("add_closers", [])))

    print(f"[refresh] Items proposed: +{total_adds}")
    print(f"[refresh] Notes: {changes.get('notes','')}")

    if total_adds < MIN_NEW_ITEMS and not force:
        print(f"[refresh] Fewer than {MIN_NEW_ITEMS} new items found — skipping personalities update.")
        _write_flag("insufficient_new_items")
        return False

    updated, n_changes = _apply_changes(personalities, changes)
    save_json(PERSONALITIES_PATH, updated)
    print(f"[refresh] personalities.json updated ({n_changes} change(s)).")

    _write_flag("updated")
    return True


def _write_flag(status: str):
    save_json(FLAG_PATH, {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
    })
    print(f"[refresh] Flag written: {status}")


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

    updated = run(force=args.force)
    if not args.no_push:
        _git_commit_and_push(updated)
