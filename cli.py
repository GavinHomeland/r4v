"""
R4V YouTube Automation CLI
Usage: python cli.py <command> [options]
"""
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

# Windows consoles default to cp1252 which can't handle emoji in video titles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json as _json

import click
from config.settings import VIDEOS_JSON, GENERATED_DIR, TRANSCRIPTS_DIR, DATA_DIR, APPLIED_DIR


_done_ids_cache: set[str] | None = None


def _done_ids() -> set[str]:
    """Return IDs of videos where work is complete: approved (True) or 'Done in Studio'.

    These are excluded from all normal pipeline steps so only new/pending videos
    are processed. Pass --all to any command to override.
    Result is memoized for the lifetime of the process — call _done_ids_invalidate()
    after generating new metadata if you need a fresh read.
    """
    global _done_ids_cache
    if _done_ids_cache is not None:
        return _done_ids_cache
    done: set[str] = set()
    for p in GENERATED_DIR.glob("*_metadata.json"):
        try:
            meta = _json.loads(p.read_text(encoding="utf-8"))
            if meta.get("approved") in (True, "external"):
                done.add(p.stem.replace("_metadata", ""))
        except Exception:
            pass
    _done_ids_cache = done
    return done


def _done_ids_invalidate() -> None:
    global _done_ids_cache
    _done_ids_cache = None


# ─────────────────────────────────────────────────────────────────────────────
# CLI group
# ─────────────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Roll4Veterans YouTube channel automation."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# discover — find all channel videos via yt-dlp
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--force", is_flag=True, help="Re-fetch even if cache exists")
@click.option("--url", default=None, help="Override channel URL")
def discover(force, url):
    """Discover all videos in the R4V channel and save to data/videos.json."""
    from r4v.channel import discover_videos
    from config.settings import CHANNEL_URL
    videos = discover_videos(url or CHANNEL_URL, force=force)
    click.echo(f"\n{len(videos)} videos saved to {VIDEOS_JSON}")



# ─────────────────────────────────────────────────────────────────────────────
# discover-unlisted — find all videos via YouTube API including unlisted
# ─────────────────────────────────────────────────────────────────────────────

@cli.command("discover-unlisted")
def discover_unlisted():
    """Find all channel videos via YouTube Data API, including unlisted ones.

    yt-dlp only sees public videos. This command uses the authenticated uploads
    playlist to find every video the channel owner can see, then merges them
    into videos.json with their correct availability (public/unlisted/private).
    """
    from r4v.auth import get_youtube_service
    from r4v.channel import discover_unlisted_via_api

    click.echo("Fetching all videos via YouTube API (includes unlisted)...")
    service = get_youtube_service()
    videos = discover_unlisted_via_api(service)
    unlisted = [v for v in videos if v.get("availability") == "unlisted"]
    click.echo(f"Done: {len(videos)} total, {len(unlisted)} unlisted.")


# ─────────────────────────────────────────────────────────────────────────────
# add-video — manually register a video by ID (for unlisted/private videos)
# ─────────────────────────────────────────────────────────────────────────────

@cli.command("add-video")
@click.argument("video_id")
def add_video(video_id):
    """Register a video by ID (e.g. an unlisted video not found by discover).

    Fetches its metadata from the YouTube API and adds it to videos.json.
    """
    from r4v.auth import get_youtube_service
    from r4v.storage import load_json, save_json

    service = get_youtube_service()
    resp = service.videos().list(part="snippet,status", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        click.echo(f"No video found for ID: {video_id} (may be private or invalid)")
        return

    item = items[0]
    snippet = item.get("snippet", {})
    status = item.get("status", {})
    privacy = status.get("privacyStatus", "public")

    video = {
        "id": video_id,
        "title": snippet.get("title", ""),
        "url": f"https://www.youtube.com/shorts/{video_id}",
        "upload_date": snippet.get("publishedAt", "")[:10].replace("-", ""),
        "description": snippet.get("description", ""),
        "tags": snippet.get("tags", []),
        "duration": None,
        "view_count": None,
        "availability": privacy,
    }

    videos = load_json(VIDEOS_JSON) or []
    existing_ids = {v["id"] for v in videos}
    if video_id in existing_ids:
        # Update existing entry
        for v in videos:
            if v["id"] == video_id:
                v.update(video)
                break
        click.echo(f"Updated existing entry: {video['title']!r} ({privacy})")
    else:
        videos.append(video)
        click.echo(f"Added: {video['title']!r} ({privacy})")

    save_json(VIDEOS_JSON, videos)


# ─────────────────────────────────────────────────────────────────────────────
# descriptions — fetch full descriptions for all discovered videos
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--force", is_flag=True, help="Re-fetch even if description already cached")
@click.option("--all", "process_all", is_flag=True, help="Include already-completed videos")
def descriptions(force, process_all):
    """Fetch current YouTube descriptions for new/pending videos (fills left pane in review GUI).

    By default skips videos already marked Approved or Done in Studio.
    Use --all to re-fetch for every video on the channel.
    """
    from r4v.channel import fetch_descriptions
    from r4v.storage import load_json

    done = set() if process_all else _done_ids()
    if done:
        click.echo(f"  Skipping {len(done)} completed videos (use --all to include them).")

    if force:
        videos = load_json(VIDEOS_JSON) or []
        for v in videos:
            if v["id"] not in done:
                v["description"] = ""
    fetch_descriptions(skip_ids=done)


# ─────────────────────────────────────────────────────────────────────────────
# transcripts — fetch transcripts for all discovered videos
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--force", is_flag=True, help="Re-fetch even if cached")
@click.option("--video-id", default=None, help="Only fetch transcript for one video ID")
@click.option("--all", "process_all", is_flag=True, help="Include already-completed videos")
def transcripts(force, video_id, process_all):
    """Fetch YouTube transcripts for new/pending videos.

    By default skips videos already marked Approved or Done in Studio.
    Use --all to attempt transcripts for every video on the channel.
    """
    from r4v.storage import load_json
    from r4v.transcript import fetch_transcript, fetch_all_transcripts

    if video_id:
        result = fetch_transcript(video_id, force=force)
        if result:
            click.echo(f"Transcript for {video_id} ({len(result['text'])} chars)")
        else:
            click.echo(f"No transcript available for {video_id}")
        return

    videos = load_json(VIDEOS_JSON)
    if not videos:
        click.echo("No videos found. Run: python cli.py discover  first.")
        return

    done = set() if process_all else _done_ids()
    ids = [v["id"] for v in videos if v["id"] not in done]
    if done:
        click.echo(f"  Skipping {len(done)} completed videos (use --all to include them).")
    results = fetch_all_transcripts(ids, force=force)
    ok = sum(1 for v in results.values() if v is not None)
    click.echo(f"\nTranscripts: {ok}/{len(ids)} fetched -> {TRANSCRIPTS_DIR}")


# ─────────────────────────────────────────────────────────────────────────────
# generate — AI-generate metadata for all videos with transcripts
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--force", is_flag=True, help="Regenerate even if already generated")
@click.option("--video-id", default=None, help="Only generate for one video ID")
def generate(force, video_id):
    """Generate AI metadata (title, description, tags, hashtags) for all videos."""
    from r4v.storage import load_json
    from r4v.transcript import fetch_transcript  # used for --video-id single-video path
    from r4v.content_gen import generate_metadata, generate_all

    videos = load_json(VIDEOS_JSON) or []
    if not videos:
        click.echo("No videos found. Run: python cli.py discover  first.")
        return

    if video_id:
        video = next((v for v in videos if v["id"] == video_id), {"id": video_id, "title": ""})
        t = fetch_transcript(video_id)
        if not t:
            click.echo(f"No transcript for {video_id}")
            return
        saved = load_json(GENERATED_DIR / f"{video_id}_metadata.json") or {}
        meta = generate_metadata(
            video_id,
            t["text"],
            existing_title=video.get("title", ""),
            existing_description=video.get("description", ""),
            transcript_urls=t.get("urls", []),
            force=force,
            ai_notes=saved.get("ai_notes", ""),
        )
        click.echo(f"\nGenerated metadata for {video_id}:")
        click.echo(f"  Title:    {meta['title']}")
        click.echo(f"  Comment:  {meta['comment']}")
        return

    # Load only cached transcripts — never attempt live fetches during generate
    from r4v.storage import load_json as _load_json
    transcripts_map = {}
    for v in videos:
        cache_path = TRANSCRIPTS_DIR / f"{v['id']}.json"
        if cache_path.exists():
            t = _load_json(cache_path)
            if t:
                transcripts_map[v["id"]] = t

    results = generate_all(videos, transcripts_map, force=force)
    click.echo(f"\nGenerated metadata for {len(results)} videos -> {GENERATED_DIR}")
    click.echo("Open review.pyw to review and approve changes before pushing.")


# ─────────────────────────────────────────────────────────────────────────────
# review — terminal diff of current vs proposed metadata
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--video-id", default=None, help="Show only one video")
def review(video_id):
    """Print current vs proposed metadata to the terminal."""
    from r4v.storage import load_json, list_pending_updates

    pending = [video_id] if video_id else list_pending_updates()
    if not pending:
        click.echo("Nothing pending review. All videos are approved or no metadata generated yet.")
        return

    for vid in pending:
        meta = load_json(GENERATED_DIR / f"{vid}_metadata.json")
        if not meta:
            continue
        click.echo(f"\n{'='*70}")
        click.echo(f"VIDEO: {vid}")
        click.echo(f"  Old title: {meta.get('existing_title', '')[:70]}")
        click.echo(f"  New title: {meta.get('title', '')[:70]}")
        click.echo(f"  Approved:  {meta.get('approved')}")
        click.echo(f"  URL:       https://youtube.com/shorts/{vid}")

    click.echo(f"\n{len(pending)} video(s) pending. Use review.pyw for full GUI review.")


# ─────────────────────────────────────────────────────────────────────────────
# push — apply approved metadata to YouTube
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--dry-run", is_flag=True, default=False, help="Preview without making changes")
@click.option("--video-id", multiple=True, help="Push specific video ID(s) — can repeat")
def push(dry_run, video_id):
    """Push approved metadata to YouTube Data API."""
    from r4v.auth import get_youtube_service
    from r4v.storage import load_json, list_approved_updates
    from r4v.youtube_api import batch_update, update_video_metadata, get_video_details

    approved_ids = list(video_id) if video_id else list_approved_updates()
    if not approved_ids:
        click.echo("No approved videos found. Approve some in review.pyw first.")
        return

    click.echo(f"{'DRY RUN — ' if dry_run else ''}Pushing {len(approved_ids)} video(s)...")

    service = get_youtube_service()
    metadata_map = {}
    for vid in approved_ids:
        meta = load_json(GENERATED_DIR / f"{vid}_metadata.json")
        if meta:
            metadata_map[vid] = meta

    results = batch_update(service, metadata_map, dry_run=dry_run)

    if dry_run:
        click.echo("\nDry run complete. Run without --dry-run to apply changes.")


# ─────────────────────────────────────────────────────────────────────────────
# engage — like + comment on all approved videos
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--video-id", multiple=True, help="Engage specific video ID(s) — can repeat")
def engage(dry_run, video_id):
    """Like and post a comment on pushed (applied) videos not yet engaged."""
    from r4v.auth import get_youtube_service
    from r4v.storage import load_json
    from r4v.engagement import run_engagement, ENGAGEMENT_LOG

    if video_id:
        target_ids = list(video_id)
    else:
        # All videos we've pushed (in applied/), minus already fully engaged
        engagement_log = load_json(ENGAGEMENT_LOG) or {}
        applied_ids = sorted({
            p.stem.replace("_applied", "")
            for p in APPLIED_DIR.glob("*_applied.json")
        })
        target_ids = [
            vid for vid in applied_ids
            if not (
                engagement_log.get(vid, {}).get("liked_jt")
                and engagement_log.get(vid, {}).get("commented_jt")
            )
        ]

    if not target_ids:
        click.echo("Nothing to engage — all pushed videos already liked and commented.")
        return

    # Build comment map from generated metadata (all 3 comment fields)
    from r4v.engagement import build_comment_map
    comment_map = build_comment_map(target_ids)

    click.echo(f"{'DRY RUN — ' if dry_run else ''}Engaging {len(target_ids)} video(s)...")

    # JT's owner account — required
    service_jt = get_youtube_service()

    # Gavin's manager account — optional; skip gracefully if token not present
    service_gavin = None
    from config.settings import TOKEN_FILE_GAVIN
    if TOKEN_FILE_GAVIN.exists():
        try:
            from r4v.auth import get_youtube_service_gavin
            service_gavin = get_youtube_service_gavin()
        except Exception as e:
            click.echo(f"  Gavin account unavailable ({e}) — skipping Gavin steps")

    run_engagement(service_jt, target_ids, comment_map, dry_run=dry_run, service_gavin=service_gavin)


# ─────────────────────────────────────────────────────────────────────────────
# check — background check used by Windows Scheduled Task
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--force", is_flag=True, help="Run even if checked recently")
def check(force):
    """Background check: discover new videos, fetch missing transcripts, auto-generate.

    Writes data/check_state.json so review.pyw can notify you on next open.
    Scheduled to run every 4 hours via Windows Task Scheduler (setup_task.py).
    """
    import datetime
    from r4v.channel import discover_videos, fetch_descriptions
    from r4v.transcript import fetch_all_transcripts
    from r4v.content_gen import generate_all
    from r4v.storage import load_json, save_json
    from config.settings import CHANNEL_URL

    MIN_INTERVAL_HOURS = 3
    state_path = DATA_DIR / "check_state.json"

    # Guard: skip if checked recently (Task Scheduler fires every 4h but guard
    # against double-runs from manual invocation or scheduler overlap)
    if not force:
        prev = load_json(state_path) or {}
        last_check = prev.get("last_check_iso", "")
        if last_check:
            try:
                last_dt = datetime.datetime.fromisoformat(last_check)
                age_h = (datetime.datetime.now() - last_dt).total_seconds() / 3600
                if age_h < MIN_INTERVAL_HOURS:
                    click.echo(
                        f"Last check was {age_h:.1f}h ago — skipping "
                        f"(min interval {MIN_INTERVAL_HOURS}h). Use --force to override."
                    )
                    return
            except ValueError:
                pass

    # 1. Discover — note which IDs are genuinely new
    click.echo("[1/4] Discovering videos...")
    known_ids = {v["id"] for v in (load_json(VIDEOS_JSON) or [])}
    videos = discover_videos(CHANNEL_URL, force=True)  # always fetch fresh to catch new uploads
    # Also discover unlisted videos via YouTube API (yt-dlp only sees the public channel page)
    try:
        from r4v.auth import get_youtube_service
        from r4v.channel import discover_unlisted_via_api
        service = get_youtube_service()
        videos = discover_unlisted_via_api(service)
    except Exception as _e:
        click.echo(f"  ! Unlisted discovery skipped: {_e}")
    new_ids = [v["id"] for v in videos if v["id"] not in known_ids]
    if new_ids:
        title_map = {v["id"]: v.get("title", v["id"]) for v in videos}
        click.echo(f"  ✓ {len(new_ids)} new video(s):")
        for vid in new_ids:
            click.echo(f"    [{vid}]  {title_map.get(vid, vid)}")
    else:
        click.echo(f"  No new videos ({len(videos)} known)")

    # 2. Fetch descriptions — only for active (non-done) videos
    done = _done_ids()
    active = [v for v in videos if v["id"] not in done]
    click.echo(f"[2/4] Fetching missing descriptions ({len(active)} active, {len(done)} done)...")
    fetch_descriptions(videos, skip_ids=done)

    # 3. Transcripts — only for active videos still missing them
    click.echo("[3/4] Fetching missing transcripts...")
    missing_t = [
        v["id"] for v in active
        if not (TRANSCRIPTS_DIR / f"{v['id']}.json").exists()
    ]
    if missing_t:
        t_results = fetch_all_transcripts(missing_t, force=False)
        newly_transcribed = [vid for vid, t in t_results.items() if t is not None]
        still_missing = [vid for vid in missing_t if vid not in newly_transcribed]
        click.echo(f"  ✓ Fetched: {len(newly_transcribed)}  Still missing: {len(still_missing)}")
    else:
        newly_transcribed = []
        still_missing = []
        click.echo("  All transcripts already cached")

    # 4. Generate — active videos with a transcript but no generated metadata yet
    click.echo("[4/4] Generating metadata for un-generated active videos with transcripts...")
    to_generate = []
    trans_map = {}
    for v in active:
        if (GENERATED_DIR / f"{v['id']}_metadata.json").exists():
            continue
        t = load_json(TRANSCRIPTS_DIR / f"{v['id']}.json")
        if t:
            to_generate.append(v)
            trans_map[v["id"]] = t
    if to_generate:
        gen_results = generate_all(to_generate, trans_map)
        newly_generated = list(gen_results.keys())
        _done_ids_invalidate()  # cache stale after new metadata written
        click.echo(f"  ✓ Generated: {len(newly_generated)}")
    else:
        newly_generated = []
        click.echo("  Nothing new to generate")

    # 4. Count all pending review
    pending_review = []
    for p in GENERATED_DIR.glob("*_metadata.json"):
        meta = load_json(p)
        if meta and meta.get("approved") is None:
            pending_review.append(p.stem.replace("_metadata", ""))

    # 5. Save state (preserve last_notified_iso so popup logic stays correct)
    prev_state = load_json(state_path) or {}
    state = {
        "last_check_iso": datetime.datetime.now().isoformat(timespec="seconds"),
        "new_video_ids": new_ids,
        "newly_generated": newly_generated,
        "needs_transcript": still_missing,
        "total_pending_review": len(pending_review),
        "last_notified_iso": prev_state.get("last_notified_iso"),
    }
    save_json(state_path, state)

    click.echo(
        f"\nDone — {len(new_ids)} new | {len(newly_generated)} generated | "
        f"{len(still_missing)} need transcripts | {len(pending_review)} pending review"
    )
    if pending_review:
        click.echo("Open review.pyw to review and approve.")


# ─────────────────────────────────────────────────────────────────────────────
# pipeline — discover → transcripts → generate (no push)
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--force", is_flag=True, help="Force re-fetch and re-generate")
@click.option("--all", "process_all", is_flag=True,
              help="Process ALL videos, including already Approved/Done-in-Studio ones")
@click.option("--skip-discover", is_flag=True,
              help="Skip discover + descriptions steps (use when videos are already registered)")
def pipeline(force, process_all, skip_discover):
    """Run full pipeline: discover → descriptions → transcripts → generate.

    By default skips videos already marked Approved or Done in Studio,
    so only new/pending videos are processed. Use --all to reprocess everything.
    Does NOT push to YouTube. Open review.pyw to approve, then run push.
    """
    from r4v.channel import discover_videos, fetch_descriptions
    from r4v.transcript import fetch_all_transcripts
    from r4v.content_gen import generate_all
    from r4v.storage import load_json
    from config.settings import CHANNEL_URL

    if skip_discover:
        click.echo("[1/4] Skipping discovery (videos already registered).")
        from r4v.storage import load_json as _lj
        from config.settings import VIDEOS_JSON as _VJ
        videos = _lj(_VJ) or []
    else:
        click.echo("[1/4] Discovering videos...")
        videos = discover_videos(CHANNEL_URL, force=True)  # always fetch fresh to catch new uploads
        # Also discover unlisted videos via YouTube API (yt-dlp only sees the public channel page)
        try:
            from r4v.auth import get_youtube_service as _get_svc
            from r4v.channel import discover_unlisted_via_api as _disc_unl
            videos = _disc_unl(_get_svc())
        except Exception as _e:
            click.echo(f"  ! Unlisted discovery skipped: {_e}")

    done = set() if process_all else _done_ids()
    active = [v for v in videos if v["id"] not in done]
    if done:
        click.echo(f"  Skipping {len(done)} completed videos — {len(active)} active"
                   f" (use --all to include completed ones).")
    if not active:
        click.echo("All videos are already completed. Use --all to reprocess.")
        return

    if skip_discover:
        click.echo(f"\n[2/4] Skipping descriptions (videos already registered).")
    else:
        click.echo(f"\n[2/4] Fetching descriptions for {len(active)} active video(s)...")
        fetch_descriptions(active)

    click.echo(f"\n[3/4] Fetching transcripts for {len(active)} active video(s)...")
    transcripts_map = fetch_all_transcripts([v["id"] for v in active], force=force)
    ok = sum(1 for v in transcripts_map.values() if v is not None)
    click.echo(f"  Transcripts: {ok}/{len(active)}")

    click.echo(f"\n[4/4] Generating metadata with Gemini AI...")
    results = generate_all(active, transcripts_map, force=force)
    click.echo(f"  Generated: {len(results)}/{len(active)}")

    # Per-video status table
    click.echo(f"\n  Status — {len(active)} active video(s):")
    for v in active:
        vid = v["id"]
        title = v.get("title", vid)[:52]
        has_t = transcripts_map.get(vid) is not None
        if vid in results and not has_t:
            tag = "✓ generated (from description)"
        elif vid in results:
            tag = "✓ generated"
        else:
            tag = "~ no transcript"
        click.echo(f"  {tag:<32}  {title}  [{vid}]")

    click.echo(f"\nPipeline complete. Open review.pyw to review and approve metadata.")


# ─────────────────────────────────────────────────────────────────────────────
# quota — show today's API quota usage
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
def quota():
    """Show today's YouTube API quota usage."""
    from r4v import quota_tracker
    click.echo(quota_tracker.report())


# ─────────────────────────────────────────────────────────────────────────────
# whoami — show which YouTube channel each token file represents
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
def whoami():
    """Show which YouTube channel each token file is authenticated as."""
    from config.settings import TOKEN_FILE_JT, TOKEN_FILE_GAVIN
    from r4v.auth import get_youtube_service

    for label, token_file in [("token_jt.json", TOKEN_FILE_JT), ("token_gavin.json", TOKEN_FILE_GAVIN)]:
        try:
            svc = get_youtube_service(token_file=token_file)
            resp = svc.channels().list(part="id,snippet", mine=True).execute()
            items = resp.get("items", [])
            if items:
                ch_id = items[0]["id"]
                ch = items[0]["snippet"]
                click.echo(f"{label}: @{ch.get('customUrl', '?').lstrip('@')}  ({ch['title']})  [{ch_id}]")
            else:
                click.echo(f"{label}: authenticated but no channel found")
        except Exception as e:
            click.echo(f"{label}: error — {e}")


# ─────────────────────────────────────────────────────────────────────────────
# transcript-log — display recent transcript fetch activity
# ─────────────────────────────────────────────────────────────────────────────

@cli.command("transcript-log")
@click.option("--tail", default=50, help="Show last N entries (0 = all)")
@click.option("--errors", is_flag=True, help="Show only failures (blocked/error/unavailable)")
def transcript_log(tail, errors):
    """Show recent transcript fetch attempts from data/transcript_log.jsonl."""
    import json
    from config.settings import TRANSCRIPT_LOG_JSONL

    if not TRANSCRIPT_LOG_JSONL.exists():
        click.echo("No transcript log found — run Transcripts first.")
        return

    lines = TRANSCRIPT_LOG_JSONL.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except Exception:
            pass

    if errors:
        entries = [e for e in entries if e.get("result") not in ("ok", "ok_ytdlp", "ok_whisper", "cache")]

    if tail and len(entries) > tail:
        entries = entries[-tail:]

    # Summary counts
    from collections import Counter
    counts = Counter(e.get("result") for e in entries if e.get("video_id") != "batch")
    click.echo(f"\nTranscript log — {TRANSCRIPT_LOG_JSONL.name}  ({len(entries)} entries shown)")
    click.echo(f"  ok(proxy): {counts['ok']}  ok(ytdlp): {counts['ok_ytdlp']}  ok(whisper): {counts['ok_whisper']}  "
               f"blocked: {counts['blocked']}  unavailable: {counts['unavailable']}  error: {counts['error']}\n")

    result_sym = {
        "ok":           "+ proxy",
        "ok_ytdlp":    "+ ytdlp",
        "ok_whisper":  "+ whispr",
        "blocked":     "X BLOCK",
        "unavailable": "- no cap",
        "error":       "! ERROR",
        "start":       "> batch",
        "done":        "< batch",
    }
    for e in entries:
        sym = result_sym.get(e.get("result"), "?")
        vid = e.get("video_id", "?")[:16]
        ts  = e.get("ts", "")[:19]
        det = e.get("detail", "")[:80]
        click.echo(f"  {ts}  {sym:<9}  {vid:<16}  {det}")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
