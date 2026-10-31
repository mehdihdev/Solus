"""Cursor pagination (§1.4): opaque urlsafe cursors over (created_at, id)."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_, or_
from sqlalchemy.orm import InstrumentedAttribute

from solus_api.core.errors import APIError

#: How far back a windowed read reaches (SOLUSDEV-321 P8): an older `since` reads from here.
READ_WINDOW: Final = timedelta(days=90)


class HasCursorFields(Protocol):
    created_at: Any
    id: Any


class PageMeta(BaseModel):
    """The §1.4 meta block `page_meta` builds, as the response model typed routes share."""

    limit: int
    has_next: bool
    next_cursor: str | None


def encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    raw = json.dumps([created_at.isoformat(), str(item_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        ts, ident = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(ts), uuid.UUID(ident)
    except (ValueError, TypeError) as exc:
        raise APIError(400, "invalid_cursor", "Malformed pagination cursor") from exc


def cursor_filter(
    created_col: InstrumentedAttribute[datetime],
    id_col: InstrumentedAttribute[uuid.UUID],
    cursor: str,
) -> ColumnElement[bool]:
    """WHERE clause selecting rows strictly after the cursor in DESC order."""
    created_at, item_id = decode_cursor(cursor)
    return or_(created_col < created_at, and_(created_col == created_at, id_col < item_id))


def page_meta(rows: list[Any], limit: int) -> tuple[list[Any], dict[str, Any]]:
    """Trim a limit+1 fetch and build the §1.4 pagination meta block."""
    has_next = len(rows) > limit
    visible = rows[:limit]
    next_cursor = (
        encode_cursor(visible[-1].created_at, visible[-1].id) if has_next and visible else None
    )
    return visible, {"limit": limit, "has_next": has_next, "next_cursor": next_cursor}


def since_floor(since: datetime | None) -> datetime:
    """`since` as an aware time (a naive one is read as UTC), no further back than `READ_WINDOW`."""
    floor = datetime.now(UTC) - READ_WINDOW
    return floor if since is None else max(since.replace(tzinfo=since.tzinfo or UTC), floor)
