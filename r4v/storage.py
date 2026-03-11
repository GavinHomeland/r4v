"""JSON persistence helpers."""
import json
from pathlib import Path
from typing import Any


def save_json(path: Path | str, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(path: Path | str) -> Any:
    path = Path(path)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_pending_updates() -> list[str]:
    """Return video IDs that have generated metadata but are not yet applied."""
    from config.settings import GENERATED_DIR, APPLIED_DIR

    generated = {p.stem.replace("_metadata", "") for p in GENERATED_DIR.glob("*_metadata.json")}
    applied = {p.stem.replace("_applied", "") for p in APPLIED_DIR.glob("*_applied.json")}
    return sorted(generated - applied)


def list_approved_updates() -> list[str]:
    """Return video IDs whose generated metadata is marked approved=True.

    approved=True  → needs pushing
    approved='external' → already pushed or done in Studio; skip
    The applied/ directory is no longer used for filtering — approved state is the source of truth.
    """
    from config.settings import GENERATED_DIR

    approved = []
    for p in GENERATED_DIR.glob("*_metadata.json"):
        data = load_json(p)
        if data and data.get("approved") is True:
            vid = p.stem.replace("_metadata", "")
            approved.append(vid)
    return sorted(approved)
