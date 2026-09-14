"""Read the checkout-local development credit allowlist as data, never shell code."""

import json
import sys
import uuid
from pathlib import Path


def read_allowlist(path: Path) -> str:
    """Missing file opts nobody in; malformed configuration stops dev startup."""
    if not path.exists():
        return ""
    if path.stat().st_size > 16384:
        raise ValueError("oversized development credit configuration")
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) != {"user_ids"}:
        raise ValueError("expected user_ids only")
    entries = value["user_ids"]
    if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
        raise ValueError("expected a list of user UUIDs")
    return ",".join(str(uuid.UUID(item)) for item in entries)


if __name__ == "__main__":
    try:
        result = read_allowlist(Path(__file__).resolve().parents[1] / ".solus-dev-credits.json")
    except (OSError, ValueError):
        sys.exit("[dev:all] invalid .solus-dev-credits.json; expected a user_ids UUID list")
    print(result)
