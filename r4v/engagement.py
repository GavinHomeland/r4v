"""Engagement automation: likes and comments via YouTube Data API.

Comment sequence per video:
  1. Location pin comment  (from JT's account  — @roll4veterans)
  2. JT voice comment      (from JT's account  — @roll4veterans)
  3. Gavin reply to JT     (from Gavin's account — @erictracy5584, posted as reply to JT's thread)

Likes: both JT's account and Gavin's account like the video.
"""
from googleapiclient.errors import HttpError

from config.settings import QUOTA_VIDEOS_RATE, QUOTA_COMMENTS_INSERT, APPLIED_DIR
from r4v import quota_tracker
from r4v.storage import load_json, save_json

ENGAGEMENT_LOG = APPLIED_DIR / "engagement.json"

# Per-video keys in engagement.json
_K_LIKED_JT        = "liked_jt"
_K_LIKED_GAVIN     = "liked_gavin"
_K_COMMENTED_LOC   = "commented_location"
_K_COMMENTED_JT    = "commented_jt"
_K_JT_THREAD_ID    = "jt_thread_id"
_K_COMMENTED_GAV   = "commented_gavin"
# Legacy compat keys (old schema)
_K_LIKED_LEGACY    = "liked"
_K_COMMENTED_LEGACY = "commented"


def _load_engagement_log() -> dict:
    data = load_json(ENGAGEMENT_LOG)
    return data if isinstance(data, dict) else {}


def _save_engagement_log(log: dict) -> None:
    save_json(ENGAGEMENT_LOG, log)


def _fully_engaged(entry: dict) -> bool:
    """Return True if all engagement steps for this video are done."""
    if entry.get(_K_LIKED_LEGACY) and entry.get(_K_COMMENTED_LEGACY):
        if not any(entry.get(k) is not None for k in (
            _K_LIKED_JT, _K_LIKED_GAVIN, _K_COMMENTED_JT, _K_COMMENTED_GAV
        )):
            return True  # legacy entry — treated as complete
    return (
        entry.get(_K_LIKED_JT)
        and entry.get(_K_COMMENTED_JT)  # True or "skipped" — both truthy
        and entry.get(_K_COMMENTED_GAV)  # True or "skipped" — both truthy
    )


# ---------------------------------------------------------------------------
# Low-level API helpers
# ---------------------------------------------------------------------------

def _like(service, video_id: str, account_label: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [engage] DRY RUN \u2014 would like {video_id} as {account_label}")
        return True
    quota_tracker.check_quota(QUOTA_VIDEOS_RATE)
    try:
        service.videos().rate(id=video_id, rating="like").execute()
        quota_tracker.consume(QUOTA_VIDEOS_RATE, f"videos.rate(like,{video_id}) as {account_label}")
        print(f"  [engage] Liked {video_id} as {account_label}")
        return True
    except HttpError as e:
        print(f"  [engage] Failed to like {video_id} as {account_label}: {e}")
        return False


def _post_top_level(service, video_id: str, text: str, account_label: str, dry_run: bool) -> str | None:
    """Post a top-level comment. Returns the comment thread ID, or None on failure."""
    if dry_run:
        print(f"  [engage] DRY RUN \u2014 top-level comment on {video_id} as {account_label}:")
        for line in text.splitlines()[:3]:
            print(f"    {line}")
        return "DRY_RUN_THREAD_ID"
    quota_tracker.check_quota(QUOTA_COMMENTS_INSERT)
    body = {
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {"snippet": {"textOriginal": text}},
        }
    }
    try:
        resp = service.commentThreads().insert(part="snippet", body=body).execute()
        quota_tracker.consume(QUOTA_COMMENTS_INSERT, f"commentThreads.insert({video_id}) as {account_label}")
        thread_id = resp["id"]
        print(f"  [engage] Posted comment on {video_id} as {account_label} (thread {thread_id})")
        return thread_id
    except HttpError as e:
        print(f"  [engage] Failed to post comment on {video_id} as {account_label}: {e}")
        return None


def _post_reply(service, thread_id: str, text: str, account_label: str, dry_run: bool) -> bool:
    """Post a reply to an existing comment thread."""
    if dry_run:
        print(f"  [engage] DRY RUN \u2014 reply to thread {thread_id} as {account_label}:")
        for line in text.splitlines()[:3]:
            print(f"    {line}")
        return True
    quota_tracker.check_quota(QUOTA_COMMENTS_INSERT)
    body = {"snippet": {"parentId": thread_id, "textOriginal": text}}
    try:
        service.comments().insert(part="snippet", body=body).execute()
        quota_tracker.consume(QUOTA_COMMENTS_INSERT, f"comments.insert(reply,{thread_id}) as {account_label}")
        print(f"  [engage] Replied to thread {thread_id} as {account_label}")
        return True
    except HttpError as e:
        print(f"  [engage] Failed to reply to {thread_id} as {account_label}: {e}")
        return False


# ---------------------------------------------------------------------------
# Main engagement runner
# ---------------------------------------------------------------------------

def run_engagement(
    service_jt,
    video_ids: list[str],
    comment_map: dict,
    dry_run: bool = True,
    service_gavin=None,
) -> dict:
    """Like and comment on a list of videos using the multi-account sequence.

    comment_map: {video_id: {"comment_location": str, "comment_jt": str, "comment_gavin": str}}
    Also accepts legacy {video_id: str} (plain comment string) for backward compat.

    service_jt    \u2014 authenticated as JT (@roll4veterans, token_jt.json)
    service_gavin \u2014 authenticated as Gavin (@erictracy5584, token_gavin.json); optional.
    """
    log = _load_engagement_log()
    results = {"liked": [], "commented": [], "skipped": [], "failed": []}

    for video_id in video_ids:
        entry = log.setdefault(video_id, {})

        if _fully_engaged(entry):
            results["skipped"].append(video_id)
            continue

        print(f"\n[engage] {'DRY RUN \u2014 ' if dry_run else ''}Processing {video_id}")

        # Support both new dict format and legacy plain-string format
        raw = comment_map.get(video_id, {})
        if isinstance(raw, str):
            raw = {"comment_jt": raw, "comment": raw}
        comment_location = raw.get("comment_location", "")
        comment_jt       = raw.get("comment_jt") or raw.get("comment", "")
        comment_gavin    = raw.get("comment_gavin", "")

        # Step 1: Like from JT's account
        if not entry.get(_K_LIKED_JT):
            if _like(service_jt, video_id, "@roll4veterans", dry_run):
                results["liked"].append(f"{video_id}:jt")
                if not dry_run:
                    entry[_K_LIKED_JT] = True
                    entry[_K_LIKED_LEGACY] = True
            else:
                results["failed"].append(f"{video_id}:like_jt")

        # Step 2: Like from Gavin's account
        if not entry.get(_K_LIKED_GAVIN):
            if service_gavin is not None:
                if _like(service_gavin, video_id, "@erictracy5584", dry_run):
                    results["liked"].append(f"{video_id}:gavin")
                    if not dry_run:
                        entry[_K_LIKED_GAVIN] = True
                else:
                    results["failed"].append(f"{video_id}:like_gavin")
            else:
                print(f"  [engage] Skipping Gavin like \u2014 token_gavin.json not set up yet")

        # Step 3: Location pin comment (JT's account)
        if comment_location and not entry.get(_K_COMMENTED_LOC):
            tid = _post_top_level(service_jt, video_id, comment_location, "@roll4veterans (map)", dry_run)
            if tid and not dry_run:
                entry[_K_COMMENTED_LOC] = True

        # Step 4: JT's voice comment (JT's account) — capture thread ID for Gavin reply
        jt_thread_id = entry.get(_K_JT_THREAD_ID)
        if not entry.get(_K_COMMENTED_JT):
            if comment_jt:
                tid = _post_top_level(service_jt, video_id, comment_jt, "@roll4veterans", dry_run)
                if tid:
                    results["commented"].append(f"{video_id}:jt")
                    if not dry_run:
                        entry[_K_COMMENTED_JT] = True
                        entry[_K_COMMENTED_LEGACY] = True
                        entry[_K_JT_THREAD_ID] = tid
                        jt_thread_id = tid
                else:
                    results["failed"].append(f"{video_id}:comment_jt")
            else:
                # No comment content — mark done so this video isn't reprocessed
                if not dry_run:
                    entry[_K_COMMENTED_JT] = "skipped"
                    entry[_K_COMMENTED_LEGACY] = True

        # Step 5: Gavin's reply to JT's comment thread
        if not entry.get(_K_COMMENTED_GAV):
            if comment_gavin:
                if service_gavin is not None and jt_thread_id:
                    if _post_reply(service_gavin, jt_thread_id, comment_gavin, "@erictracy5584", dry_run):
                        results["commented"].append(f"{video_id}:gavin")
                        if not dry_run:
                            entry[_K_COMMENTED_GAV] = True
                    else:
                        results["failed"].append(f"{video_id}:comment_gavin")
                elif service_gavin is None:
                    print(f"  [engage] Skipping Gavin reply \u2014 token_gavin.json not set up yet")
                elif not jt_thread_id:
                    print(f"  [engage] Skipping Gavin reply \u2014 JT thread ID unknown (JT comment not posted yet)")
            else:
                # No comment content — mark done so this video isn't reprocessed
                if not dry_run:
                    entry[_K_COMMENTED_GAV] = "skipped"

        if not dry_run:
            _save_engagement_log(log)

    if dry_run:
        _save_engagement_log(log)

    jt_likes    = sum(1 for x in results["liked"]    if x.endswith(":jt"))
    gavin_likes = sum(1 for x in results["liked"]    if x.endswith(":gavin"))
    jt_cmts     = sum(1 for x in results["commented"] if x.endswith(":jt"))
    gavin_cmts  = sum(1 for x in results["commented"] if x.endswith(":gavin"))
    print(f"\n[engage] {'DRY RUN \u2014 ' if dry_run else ''}Summary:")
    print(f"  Liked (JT/Gavin):      {jt_likes} / {gavin_likes}")
    print(f"  Commented (JT/Gavin):  {jt_cmts} / {gavin_cmts}")
    print(f"  Skipped:               {len(results['skipped'])}")
    print(f"  Failed:                {len(results['failed'])}")
    print(f"  {quota_tracker.report()}")
    return results


def build_comment_map(video_ids: list[str]) -> dict[str, dict]:
    """Load all comment fields from generated metadata for a list of video IDs."""
    from config.settings import GENERATED_DIR as _GD
    result = {}
    for vid in video_ids:
        meta = load_json(_GD / f"{vid}_metadata.json")
        if meta:
            result[vid] = {
                "comment_location": meta.get("comment_location", ""),
                "comment_jt":       meta.get("comment_jt") or meta.get("comment", ""),
                "comment_gavin":    meta.get("comment_gavin", ""),
                "comment":          meta.get("comment", ""),
            }
    return result
