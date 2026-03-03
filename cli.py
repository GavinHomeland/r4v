"""
R4V YouTube Automation CLI
Usage: python cli.py <command> [options]
"""
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

import click
from config.settings import VIDEOS_JSON, GENERATED_DIR, TRANSCRIPTS_DIR, DATA_DIR


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
# descriptions — fetch full descriptions for all discovered videos
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--force", is_flag=True, help="Re-fetch even if description already cached")
def descriptions(force):
    """Fetch current YouTube descriptions for all videos (fills left pane in review GUI)."""
    from r4v.channel import fetch_descriptions
    from r4v.storage import load_json
    if force:
        # Clear existing descriptions so all are re-fetched
        videos = load_json(VIDEOS_JSON) or []
        for v in videos:
            v["description"] = ""
    fetch_descriptions()


# ─────────────────────────────────────────────────────────────────────────────
# transcripts — fetch transcripts for all discovered videos
# ─────────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--force", is_flag=True, help="Re-fetch even if cached")
@click.option("--video-id", default=None, help="Only fetch transcript for one video ID")
def transcripts(force, video_id):
    """Fetch YouTube transcripts for all videos."""
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

    ids = [v["id"] for v in videos]
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
        meta = generate_metadata(
            video_id,
            t["text"],
            existing_title=video.get("title", ""),
            existing_description=video.get("description", ""),
            transcript_urls=t.get("urls", []),
            force=force,
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
@click.option("--video-id", default=None, help="Push only one video")
def push(dry_run, video_id):
    """Push approved metadata to YouTube Data API."""
    from r4v.auth import get_youtube_service
    from r4v.storage import load_json, list_approved_updates
    from r4v.youtube_api import batch_update, update_video_metadata, get_video_details

    approved_ids = [video_id] if video_id else list_approved_updates()
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
@click.option("--video-id", default=None)
def engage(dry_run, video_id):
    """Like and post a comment on approved videos."""
    from r4v.auth import get_youtube_service
    from r4v.storage import load_json, list_approved_updates
    from r4v.engagement import run_engagement

    approved_ids = [video_id] if video_id else list_approved_updates()
    if not approved_ids:
        click.echo("No approved videos. Approve some in review.pyw first.")
        return

    # Build comment map — skip videos flagged as needing JT's personal comment
    comment_map = {}
    jt_skipped = []
    for vid in approved_ids:
        meta = load_json(GENERATED_DIR / f"{vid}_metadata.json")
        if not meta:
            continue
        if meta.get("needs_jt_comment"):
            jt_skipped.append(vid)
            continue
        if meta.get("comment"):
            comment_map[vid] = meta["comment"]

    if jt_skipped:
        click.echo(f"  Skipping {len(jt_skipped)} video(s) flagged 'Needs JT Comment': "
                   f"{', '.join(jt_skipped)}")

    click.echo(f"{'DRY RUN — ' if dry_run else ''}Engaging {len(approved_ids)} video(s)...")
    service = get_youtube_service()
    run_engagement(service, approved_ids, comment_map, dry_run=dry_run)


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
    from r4v.channel import discover_videos
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
    click.echo("[1/3] Discovering videos...")
    known_ids = {v["id"] for v in (load_json(VIDEOS_JSON) or [])}
    videos = discover_videos(CHANNEL_URL, force=False)
    new_ids = [v["id"] for v in videos if v["id"] not in known_ids]
    if new_ids:
        click.echo(f"  ✓ {len(new_ids)} new video(s): {', '.join(new_ids)}")
    else:
        click.echo(f"  No new videos ({len(videos)} known)")

    # 2. Transcripts — only attempt ones still missing
    click.echo("[2/3] Fetching missing transcripts...")
    missing_t = [
        v["id"] for v in videos
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

    # 3. Generate — only for newly transcribed videos without existing metadata
    click.echo("[3/3] Generating metadata for newly transcribed videos...")
    to_generate = [
        v for v in videos
        if v["id"] in newly_transcribed
        and not (GENERATED_DIR / f"{v['id']}_metadata.json").exists()
    ]
    if to_generate:
        trans_map = {}
        for v in to_generate:
            t = load_json(TRANSCRIPTS_DIR / f"{v['id']}.json")
            if t:
                trans_map[v["id"]] = t
        gen_results = generate_all(to_generate, trans_map)
        newly_generated = list(gen_results.keys())
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
@click.option("--new-only", is_flag=True, help="Only process videos not yet discovered")
def pipeline(force, new_only):
    """Run full pipeline: discover → transcripts → generate.

    Does NOT push to YouTube. Open review.pyw to approve, then run push.
    """
    from r4v.channel import discover_videos, get_new_videos
    from r4v.transcript import fetch_all_transcripts
    from r4v.content_gen import generate_all
    from r4v.storage import load_json
    from config.settings import CHANNEL_URL

    click.echo("[1/3] Discovering videos...")
    if new_only:
        videos = get_new_videos(CHANNEL_URL)
        if not videos:
            click.echo("No new videos. Exiting.")
            return
    else:
        videos = discover_videos(CHANNEL_URL, force=force)

    click.echo(f"\n[2/3] Fetching transcripts for {len(videos)} video(s)...")
    transcripts_map = fetch_all_transcripts([v["id"] for v in videos], force=force)
    ok = sum(1 for v in transcripts_map.values() if v is not None)
    click.echo(f"  Transcripts: {ok}/{len(videos)}")

    click.echo(f"\n[3/3] Generating metadata with Claude AI...")
    results = generate_all(videos, transcripts_map, force=force)
    click.echo(f"  Generated: {len(results)}/{len(videos)}")

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

if __name__ == "__main__":
    cli()
