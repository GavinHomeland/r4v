"""Daily YouTube API quota tracking with PT midnight reset."""
import datetime
import zoneinfo
from config.settings import QUOTA_LOG_JSON, QUOTA_DAILY_LIMIT
from r4v.storage import load_json, save_json

_MAX_OPS = 200  # cap on stored operations entries


class QuotaExceededError(Exception):
    pass


def _today_pt() -> str:
    pt = zoneinfo.ZoneInfo("America/Los_Angeles")
    return datetime.datetime.now(pt).strftime("%Y-%m-%d")


def _load_log() -> dict:
    data = load_json(QUOTA_LOG_JSON)
    today = _today_pt()
    if not data or data.get("date") != today:
        return {"date": today, "used": 0, "operations": []}
    return data


def get_used() -> int:
    return _load_log()["used"]


def get_remaining() -> int:
    return QUOTA_DAILY_LIMIT - get_used()


def check_quota(units_needed: int) -> None:
    """Raise QuotaExceededError if spending units_needed would exceed today's limit."""
    remaining = get_remaining()
    if units_needed > remaining:
        raise QuotaExceededError(
            f"Quota guard: need {units_needed} units but only {remaining} remaining today "
            f"(limit: {QUOTA_DAILY_LIMIT})"
        )


def consume(units: int, operation: str = "") -> None:
    """Record quota consumption."""
    log = _load_log()
    log["used"] += units
    log["operations"].append({"op": operation, "units": units})
    # Prune to last _MAX_OPS entries so the file doesn't grow unbounded
    if len(log["operations"]) > _MAX_OPS:
        log["operations"] = log["operations"][-_MAX_OPS:]
    save_json(QUOTA_LOG_JSON, log)


def report() -> str:
    log = _load_log()
    return (
        f"Quota ({log['date']}): {log['used']} used / {QUOTA_DAILY_LIMIT} limit "
        f"({get_remaining()} remaining)"
    )
