"""Engagement automation: likes and comments via YouTube Data API."""
from googleapiclient.errors import HttpError

from config.settings import QUOTA_VIDEOS_RATE, QUOTA_COMMENTS_INSERT, APPLIED_DIR
from r4v import quota_tracker
from r4v.storage import load_json, save_json

ENGAGEMENT_LOG = APPLIED_DIR / "engagement.json"


def _load_engagement_log() -> dict:
    data = load_json(ENGAGEMENT_LOG)
    return data if isinstance(data, dict) else {}


def _save_engagement_log(log: dict) -> None:
    save_json(ENGAGEMENT_LOG, log)


def like_video(service, video_id: str, dry_run: bool = False) -> bool:
    """Like a video (costs 50 quota units)."""
    if dry_run:
        print(f"[engagement] DRY RUN — would like {video_id}")
        return True
    quota_tracker.check_quota(QUOTA_VIDEOS_RATE)
    try:
        service.videos().rate(id=video_id, rating="like").execute()
        quota_tracker.consume(QUOTA_VIDEOS_RATE, f"videos.rate(like, {video_id})")
        print(f"[engagement] Liked {video_id}")
        return True
    except HttpError as e:
        print(f"[engagement] Failed to like {video_id}: {e}")
        return False


def post_comment(service, video_id: str, comment_text: str, dry_run: bool = False) -> bool:
    """Post a top-level comment on a video (costs 50 quota units)."""
    if dry_run:
        print(f"[engagement] DRY RUN — would comment on {video_id}:")
        print(f"  {comment_text[:120]}")
        return True
    quota_tracker.check_quota(QUOTA_COMMENTS_INSERT)
    body = {
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {
                "snippet": {"textOriginal": comment_text}
            },
        }
    }
    try:
        service.commentThreads().insert(part="snippet", body=body).execute()
        quota_tracker.consume(QUOTA_COMMENTS_INSERT, f"commentThreads.insert({video_id})")
        print(f"[engagement] Commented on {video_id}")
        return True
    except HttpError as e:
        print(f"[engagement] Failed to comment on {video_id}: {e}")
        return False


def run_engagement(
    service,
    video_ids: list[str],
    comment_map: dict[str, str],
    dry_run: bool = True,
) -> dict:
    """Like and comment on a list of videos.

    comment_map: {video_id: comment_text}
    Skips videos already processed in engagement.json.
    """
    log = _load_engagement_log()
    results = {"liked": [], "commented": [], "skipped": [], "failed": []}

    for video_id in video_ids:
        already_liked = log.get(video_id, {}).get("liked", False)
        already_commented = log.get(video_id, {}).get("commented", False)

        if already_liked and already_commented:
            results["skipped"].append(video_id)
            continue

        entry = log.setdefault(video_id, {"liked": False, "commented": False})

        if not already_liked:
            if like_video(service, video_id, dry_run=dry_run):
                results["liked"].append(video_id)
                if not dry_run:
                    entry["liked"] = True
            else:
                results["failed"].append(video_id)

        comment = comment_map.get(video_id, "")
        if comment and not already_commented:
            if post_comment(service, video_id, comment, dry_run=dry_run):
                results["commented"].append(video_id)
                if not dry_run:
                    entry["commented"] = True
            else:
                results["failed"].append(video_id)

    if not dry_run:
        _save_engagement_log(log)

    print(f"\n[engagement] {'DRY RUN — ' if dry_run else ''}Summary:")
    print(f"  Liked: {len(results['liked'])}")
    print(f"  Commented: {len(results['commented'])}")
    print(f"  Skipped (already done): {len(results['skipped'])}")
    print(f"  Failed: {len(results['failed'])}")
    print(f"  {quota_tracker.report()}")
    return results
