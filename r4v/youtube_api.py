"""YouTube Data API v3 read/write operations."""
from googleapiclient.errors import HttpError

from config.settings import (
    QUOTA_VIDEOS_LIST,
    QUOTA_VIDEOS_UPDATE,
    QUOTA_PLAYLIST_INSERT,
    PLAYLIST_ID,
    APPLIED_DIR,
)
from r4v import quota_tracker
from r4v.storage import save_json, load_json


def get_video_details(service, video_id: str) -> dict | None:
    """Fetch current metadata for a single video (costs 1 quota unit)."""
    quota_tracker.check_quota(QUOTA_VIDEOS_LIST)
    try:
        resp = service.videos().list(
            part="snippet,status",
            id=video_id,
        ).execute()
        quota_tracker.consume(QUOTA_VIDEOS_LIST, f"videos.list({video_id})")
    except HttpError as e:
        print(f"[youtube_api] Error fetching {video_id}: {e}")
        return None

    items = resp.get("items", [])
    if not items:
        print(f"[youtube_api] Video not found: {video_id}")
        return None

    item = items[0]
    snippet = item.get("snippet", {})
    return {
        "id": video_id,
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "tags": snippet.get("tags", []),
        "categoryId": snippet.get("categoryId", "22"),
        "defaultLanguage": snippet.get("defaultLanguage", "en"),
        "privacyStatus": item.get("status", {}).get("privacyStatus", "public"),
    }


def update_video_metadata(
    service,
    video_id: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "22",
    make_public: bool = True,
    publish_at: str = "",
    dry_run: bool = False,
) -> bool:
    """Update video title, description, tags, and optionally set visibility.

    publish_at: RFC 3339 UTC timestamp (e.g. "2026-03-20T21:00:00Z"). When set,
    the video stays private with a scheduled release — make_public is ignored.
    Costs 50 quota units. Returns True on success (or in dry_run mode).
    """
    # Strip [[ editor instruction lines before pushing to YouTube
    description = "\n".join(
        line for line in description.splitlines()
        if not line.strip().startswith("[[")
    ).strip()

    if dry_run:
        print(f"[youtube_api] DRY RUN — would update {video_id}:")
        print(f"  Title: {title[:80]}")
        print(f"  Description: {description[:120]}...")
        print(f"  Tags: {tags[:5]}...")
        if publish_at:
            print(f"  Visibility: → scheduled {publish_at}")
        elif make_public:
            print(f"  Visibility: → public")
        return True

    quota_tracker.check_quota(QUOTA_VIDEOS_UPDATE)
    parts = ["snippet"]
    body = {
        "id": video_id,
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
    }
    if publish_at:
        parts.append("status")
        body["status"] = {"privacyStatus": "private", "publishAt": publish_at}
    elif make_public:
        parts.append("status")
        body["status"] = {"privacyStatus": "public"}
    try:
        service.videos().update(part=",".join(parts), body=body).execute()
        quota_tracker.consume(QUOTA_VIDEOS_UPDATE, f"videos.update({video_id})")
        if publish_at:
            print(f"[youtube_api] Scheduled {video_id}: {title[:60]} → {publish_at}")
        else:
            visibility = " + made public" if make_public else ""
            print(f"[youtube_api] Updated {video_id}: {title[:60]}{visibility}")
        return True
    except HttpError as e:
        print(f"[youtube_api] Failed to update {video_id}: {e}")
        return False


def add_to_playlist(
    service,
    video_id: str,
    playlist_id: str = PLAYLIST_ID,
    dry_run: bool = False,
) -> bool:
    """Add a video to a playlist (costs 50 quota units).

    Silently skips if the video is already in the playlist.
    Returns True on success/already-present (or in dry_run), False on failure.
    """
    if dry_run:
        print(f"[youtube_api] DRY RUN — would add {video_id} to playlist {playlist_id}")
        return True

    quota_tracker.check_quota(QUOTA_PLAYLIST_INSERT)
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    try:
        service.playlistItems().insert(part="snippet", body=body).execute()
        quota_tracker.consume(QUOTA_PLAYLIST_INSERT, f"playlistItems.insert({video_id})")
        print(f"[youtube_api] Added {video_id} to playlist")
        return True
    except HttpError as e:
        # 409 = video already in playlist — not an error
        if e.resp.status == 409:
            print(f"[youtube_api] {video_id} already in playlist — skipped")
            return True
        print(f"[youtube_api] Failed to add {video_id} to playlist: {e}")
        return False


def batch_update(service, metadata_map: dict[str, dict], dry_run: bool = True) -> dict:
    """Apply metadata updates for all approved videos.

    For each approved video:
      1. Update title / description / tags (videos.update — 50 units)
      2. Set visibility → public (bundled in same call, 0 extra units)
      3. Add to Roll for Veterans playlist (playlistItems.insert — 50 units)

    metadata_map: {video_id: metadata_dict from content_gen}
    Returns summary dict.
    """
    results = {"updated": [], "skipped": [], "failed": [], "dry_run": dry_run}

    for video_id, meta in metadata_map.items():
        if not meta.get("approved"):
            results["skipped"].append(video_id)
            continue

        # Fetch current category to preserve it
        current = get_video_details(service, video_id)
        cat_id = current["categoryId"] if current else "22"

        ok = update_video_metadata(
            service,
            video_id=video_id,
            title=meta["title"],
            description=meta["description"],
            tags=meta.get("tags", []),
            category_id=cat_id,
            make_public=True,
            publish_at=meta.get("publish_at", ""),
            dry_run=dry_run,
        )

        if ok:
            # Add to playlist regardless of dry_run (add_to_playlist handles that internally)
            add_to_playlist(service, video_id, dry_run=dry_run)

        if ok and not dry_run:
            results["updated"].append(video_id)
            # Record in applied/
            applied_path = APPLIED_DIR / f"{video_id}_applied.json"
            save_json(applied_path, {"video_id": video_id, "metadata": meta})
        elif ok:
            results["updated"].append(video_id)
        else:
            results["failed"].append(video_id)

    print(f"\n[batch_update] {'DRY RUN — ' if dry_run else ''}Summary:")
    print(f"  Updated: {len(results['updated'])}")
    print(f"  Skipped (not approved): {len(results['skipped'])}")
    print(f"  Failed: {len(results['failed'])}")
    print(f"  {quota_tracker.report()}")
    return results
